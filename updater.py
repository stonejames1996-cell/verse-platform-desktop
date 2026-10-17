"""
Auto update from GitHub Releases.

Every release the GitHub workflow publishes includes "VersePlatformSetup.exe". The app checks
the latest release a minute after starting and then every 6 hours. When a newer version is out
it downloads the installer quietly, checks it, and then:
  * installs it straight away if nothing is being recorded and the window isn't open
    (for example right after Windows starts), or
  * offers "Update now" in the tray and in My clips, and installs it next time the app quits.
The installer runs silently, keeps settings and clips, and reopens the app when it's done.
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.request

from rewind_core import APP_VERSION, UPDATE_REPO

log = logging.getLogger("verse.update")

ASSET_NAME = "VersePlatformSetup.exe"
CHECK_EVERY = 2 * 3600
FOLDER = os.path.join(tempfile.gettempdir(), "VersePlatformUpdate")
UA = f"VersePlatform/{APP_VERSION}"


def _ver(s):
    """'v1.2.10' -> (1, 2, 10)"""
    return tuple(int(x) for x in re.findall(r"\d+", s or "")[:3]) or (0,)


class Updater:
    def __init__(self, on_ready):
        self.on_ready = on_ready          # called with the new version once the installer is downloaded
        self.version = ""                 # newer version that's ready to install
        self.notes = ""
        self.path = ""
        self.installing = False
        self._busy = threading.Lock()

    @property
    def enabled(self):
        return bool(UPDATE_REPO) and "/" in UPDATE_REPO

    def cleanup(self):
        """Removes installers for versions that are already installed."""
        try:
            for f in os.listdir(FOLDER):
                m = re.fullmatch(r"VersePlatformSetup-v(\d+\.\d+\.\d+)\.exe(\.part)?", f)
                if m and _ver(m.group(1)) <= _ver(APP_VERSION):
                    os.remove(os.path.join(FOLDER, f))
        except OSError:
            pass

    def start(self):
        self.cleanup()
        if not self.enabled:
            log.info("Auto update is off (no UPDATE_REPO set)")
            return
        threading.Thread(target=self._loop, daemon=True).start()

    def pending_on_disk(self):
        """An update downloaded (and checked) by an earlier run that never got installed."""
        best = None
        try:
            for f in os.listdir(FOLDER):
                m = re.fullmatch(r"VersePlatformSetup-v(\d+\.\d+\.\d+)\.exe", f)
                if m and _ver(m.group(1)) > _ver(APP_VERSION) and (not best or _ver(m.group(1)) > _ver(best[0])):
                    best = (m.group(1), os.path.join(FOLDER, f))
        except OSError:
            pass
        return best

    def use_pending(self):
        found = self.pending_on_disk()
        if found:
            self.version, self.path = found
            log.info("Update %s was already downloaded", self.version)
        return bool(found)

    def _loop(self):
        time.sleep(8)  # let recording and the window settle first
        while True:
            try:
                self.check()
            except Exception:
                log.warning("Update check failed", exc_info=True)
            time.sleep(CHECK_EVERY)

    def check(self):
        if self.version or not self._busy.acquire(blocking=False):
            return
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                                         headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                rel = json.load(r)
            latest = rel.get("tag_name", "")
            if _ver(latest) <= _ver(APP_VERSION):
                log.info("Up to date (%s, latest %s)", APP_VERSION, latest)
                return
            asset = next((a for a in rel.get("assets", []) if a.get("name") == ASSET_NAME), None)
            if not asset:
                log.warning("Release %s has no %s", latest, ASSET_NAME)
                return
            path = self._download(asset, latest)
            self.version = latest.lstrip("v")
            self.notes = (rel.get("body") or "").strip()
            self.path = path
            log.info("Update %s downloaded to %s", self.version, path)
            self.on_ready(self.version)
        finally:
            self._busy.release()

    def _download(self, asset, tag):
        os.makedirs(FOLDER, exist_ok=True)
        path = os.path.join(FOLDER, f"VersePlatformSetup-{tag}.exe")
        if os.path.exists(path) and asset.get("size") and os.path.getsize(path) == asset["size"]:
            return path  # already downloaded by an earlier run
        part = path + ".part"
        h = hashlib.sha256()
        req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                f.write(chunk)
        size = os.path.getsize(part)
        if asset.get("size") and size != asset["size"]:
            os.remove(part)
            raise IOError(f"Update download was incomplete ({size} of {asset['size']} bytes)")
        digest = asset.get("digest") or ""   # GitHub gives "sha256:<hex>" for release files
        if digest.startswith("sha256:") and digest[7:].lower() != h.hexdigest():
            os.remove(part)
            raise IOError("Update download didn't match GitHub's checksum")
        os.replace(part, path)
        return path

    def install(self, relaunch=True, background=False):
        """Start the silent installer. The caller should quit the app straight after."""
        if not self.path or not os.path.exists(self.path) or self.installing:
            return False
        self.installing = True
        log.info("Installing update %s", self.version)
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        args = [self.path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
        if relaunch:
            args.append("/RELAUNCH=background" if background else "/RELAUNCH")
        subprocess.Popen(args, creationflags=flags, close_fds=True)
        return True
