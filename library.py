"""
Clip library: keeps track of every saved clip (game, length, thumbnail, posted to Verse or not),
makes trimmed copies for posting, and serves clips + thumbnails to the app window through a
tiny local web server on 127.0.0.1. Clips never leave the PC unless the player posts one.
"""

import datetime
import re
import http.server
import json
import logging
import os
import secrets
import socketserver
import subprocess
import threading
import time
import urllib.parse
import uuid

log = logging.getLogger("Verse Platform")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# websites allowed to read clips from this PC (only when the player hits Publish)
ALLOWED_ORIGINS = {"https://verseplatform.gg", "https://www.verseplatform.gg",
                   "https://verse-platform-ac398069.base44.app"}


def probe_duration(ff, path):
    try:
        r = subprocess.run([ff, "-hide_banner", "-i", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=20, creationflags=NO_WINDOW)
        m = re.search(rb"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
        if m:
            h, mi, sec = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(sec)
    except Exception:
        pass
    return 0.0


def probe_height(ff, path):
    try:
        r = subprocess.run([ff, "-hide_banner", "-i", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=20, creationflags=NO_WINDOW)
        m = re.search(rb"Video:.*?, (\d{2,5})x(\d{2,5})", r.stderr)
        if m:
            return int(m.group(2))
    except Exception:
        pass
    return 1080


LOW_PRIORITY = 0x00004000 if os.name == "nt" else 0   # BELOW_NORMAL_PRIORITY_CLASS, so games stay smooth


def recycle(paths):
    """Moves files to the Windows Recycle Bin. Elsewhere (testing on Linux) just deletes them."""
    if os.name != "nt":
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass
        return
    import ctypes
    from ctypes import wintypes as wt

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wt.HWND), ("wFunc", wt.UINT), ("pFrom", ctypes.c_void_p), ("pTo", ctypes.c_void_p),
                    ("fFlags", wt.WORD), ("fAnyOperationsAborted", wt.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wt.LPCWSTR)]
    text = "\0".join(os.path.abspath(p) for p in paths) + "\0\0"   # list ends with a double null
    buf = (ctypes.c_wchar * len(text))(*text)
    op = SHFILEOPSTRUCTW(None, 3, ctypes.cast(buf, ctypes.c_void_p), None,
                         0x0004 | 0x0010 | 0x0040 | 0x0400, 0, None, None)  # silent, no prompts, allow undo, no error UI
    sh = ctypes.WinDLL("shell32")
    sh.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
    r = sh.SHFileOperationW(ctypes.byref(op))
    if r:
        log.warning("Recycle Bin move returned %s", r)


class ExportError(Exception):
    pass


class ClipLibrary:
    def __init__(self, clips_folder, data_dir, ff):
        self.ff = ff
        self.clips_folder = clips_folder
        self.thumb_dir = os.path.join(data_dir, "thumbnails")
        self.export_dir = os.path.join(data_dir, "exports")
        os.makedirs(self.export_dir, exist_ok=True)
        self.index_path = os.path.join(data_dir, "clips.json")
        os.makedirs(self.thumb_dir, exist_ok=True)
        self.lock = threading.RLock()
        self.clips = {}
        self.matches_path = os.path.join(data_dir, "matches.json")
        self.matches = {}   # one entry per League match: mode, champion, result, K/D/A...
        try:
            with open(self.matches_path, encoding="utf-8") as f:
                self.matches = {m["id"]: m for m in json.load(f)}
        except Exception:
            pass
        try:
            with open(self.index_path, encoding="utf-8") as f:
                for c in json.load(f):
                    self.clips[c["id"]] = c
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("Clip list unreadable, rebuilding it (%s)", e)

    # ---- storage
    def _save(self):
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(self.clips.values()), f, indent=1)
        os.replace(tmp, self.index_path)

    def save_match(self, match):
        with self.lock:
            if self.matches.get(match["id"]) == match:
                return
            self.matches[match["id"]] = dict(match)
            tmp = self.matches_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(list(self.matches.values()), f, indent=1)
            os.replace(tmp, self.matches_path)

    def list_matches(self):
        with self.lock:
            used = {c.get("match") for c in self.clips.values()}
            return [dict(m) for m in self.matches.values() if m["id"] in used]

    def abs_path(self, clip):
        return os.path.join(self.clips_folder, clip["path"])

    def thumb_path(self, clip):
        return os.path.join(self.thumb_dir, clip["thumb"]) if clip.get("thumb") else ""

    def list(self):
        with self.lock:
            return sorted((dict(c) for c in self.clips.values()), key=lambda c: c.get("created", ""), reverse=True)

    def get(self, clip_id):
        with self.lock:
            c = self.clips.get(clip_id)
            return dict(c) if c else None

    # ---- adding clips
    def add(self, path, game="", highlight="", match=None):
        rel = os.path.relpath(path, self.clips_folder)
        with self.lock:
            for c in self.clips.values():
                if c["path"] == rel:
                    return c
        with self.lock:
            if match:   # inside a match folder: "Clip 1", "Clip 2"... for the ones saved with the key
                number = 1 + sum(1 for c in self.clips.values() if c.get("match") == match and not c.get("highlight"))
                title = highlight or f"Clip {number}"
            else:
                number = 1 + sum(1 for c in self.clips.values() if c.get("game", "") == game)
                title = highlight or f"{game or 'Clip'} #{number}"
        clip = {
            "id": uuid.uuid4().hex[:12],
            "path": rel,
            "title": title,
            "game": game,
            "highlight": highlight,
            "match": match,
            "created": datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds"),
            "duration": round(probe_duration(self.ff, path), 1),
            "size": os.path.getsize(path),
            "thumb": "",
            "posted": None,   # {"at": "...", "url": "..."} once it's on Verse
        }
        clip["thumb"] = self._make_thumb(path, clip["id"], clip["duration"])
        with self.lock:
            self.clips[clip["id"]] = clip
            self._save()
        return clip

    def _make_thumb(self, path, clip_id, duration):
        name = f"{clip_id}.jpg"
        at = str(min(3.0, max(0.0, (duration or 2) / 2)))
        try:
            subprocess.run([self.ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", at, "-i", path,
                            "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", os.path.join(self.thumb_dir, name)],
                           timeout=30, creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        return name if os.path.exists(os.path.join(self.thumb_dir, name)) else ""

    def scan(self):
        """Picks up clips made before the library existed, and forgets deleted ones."""
        found = set()
        if os.path.isdir(self.clips_folder):
            for root, _, files in os.walk(self.clips_folder):
                for fn in files:
                    if fn.lower().endswith(".mp4") and not fn.lower().endswith(".wm.mp4"):
                        full = os.path.join(root, fn)
                        found.add(os.path.relpath(full, self.clips_folder))
        with self.lock:
            known = {c["path"] for c in self.clips.values()}
            gone = [cid for cid, c in self.clips.items() if c["path"] not in found]
            for cid in gone:
                self.clips.pop(cid, None)
            if gone:
                self._save()
        with self.lock:
            by_folder = {m.get("folder"): m["id"] for m in self.matches.values() if m.get("folder")}
        for rel in sorted(found - known):
            parts = rel.replace("\\", "/").split("/")
            game = parts[0] if len(parts) > 1 else ""
            match = by_folder.get(parts[1]) if len(parts) > 2 else None
            self.add(os.path.join(self.clips_folder, rel), game=game, match=match)

    # ---- changes
    def mark_posted(self, clip_id, url=""):
        with self.lock:
            if clip_id in self.clips:
                self.clips[clip_id]["posted"] = {"at": datetime.datetime.now().isoformat(timespec="seconds"),
                                                 "url": url}
                self._save()

    def rename(self, clip_id, title):
        with self.lock:
            if clip_id in self.clips:
                self.clips[clip_id]["title"] = title.strip()[:120] or self.clips[clip_id]["title"]
                self._save()

    def delete(self, clip_id):
        return self.delete_many([clip_id])

    def delete_many(self, clip_ids):
        """Sends the clips' videos to the Recycle Bin (so a mistake can be undone) and forgets them.
        Returns (deleted, failed) counts. A clip whose file can't be moved (open somewhere) is kept."""
        with self.lock:
            picked = [(cid, self.clips[cid]) for cid in dict.fromkeys(clip_ids) if cid in self.clips]
        videos = [self.abs_path(c) for _, c in picked if os.path.exists(self.abs_path(c))]
        if videos:
            recycle(videos)
        deleted = failed = 0
        folders = set()
        with self.lock:
            for cid, c in picked:
                path = self.abs_path(c)
                if os.path.exists(path):
                    failed += 1
                    continue
                for p in (self.thumb_path(c), self.export_path(cid), path + ".wm.mp4"):
                    try:
                        if p and os.path.exists(p):
                            os.remove(p)
                    except OSError:
                        pass
                self.clips.pop(cid, None)
                folders.add(os.path.dirname(path))
                deleted += 1
            if deleted:
                self._save()
        for d in folders:  # tidy up a match folder that's now empty (never the main clips folder)
            try:
                if os.path.normcase(os.path.abspath(d)) != os.path.normcase(os.path.abspath(self.clips_folder)) \
                        and os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass
        return deleted, failed

    # ---- posting
    def export_path(self, clip_id):
        return os.path.join(self.export_dir, f"{clip_id}.mp4")

    def export(self, clip_id, start, end, encoder="libx264", max_seconds=60, watermark=False):
        """Makes the copy that gets posted: the part between start and end (seconds),
        at most max_seconds long. Cutting on the 2 second keyframes is instant and lossless;
        any other cut point is re-encoded (fast on the GPU)."""
        clip = self.get(clip_id)
        if not clip:
            raise ExportError("That clip isn't on this PC any more")
        src = self.abs_path(clip)
        dur = clip.get("duration") or probe_duration(self.ff, src)
        start = max(0.0, float(start or 0))
        end = min(float(end or dur), dur) if dur else float(end or 0)
        if end - start > max_seconds + 0.05:
            start = end - max_seconds
        if end - start < 1:
            raise ExportError("Pick at least 1 second of the clip")
        out = self.export_path(clip_id)
        whole = start < 0.05 and (not dur or end > dur - 0.05)
        on_keyframes = abs(start / 2 - round(start / 2)) < 0.01
        # the saved clip already starts with the watermark. If the start was trimmed off, add it again
        wm = watermark and start >= 0.05
        if wm:
            on_keyframes = False
        if whole:
            cmd = [self.ff, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-map", "0", "-c", "copy",
                   "-movflags", "+faststart", out]
        elif on_keyframes:
            cmd = [self.ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-i", src,
                   "-t", f"{end - start:.3f}", "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero",
                   "-movflags", "+faststart", out]
        else:
            cmd = self._encode_cmd(src, start, end, out, encoder, wm)
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600, creationflags=NO_WINDOW)
        if r.returncode != 0 and encoder != "libx264" and not whole and not on_keyframes:
            log.warning("GPU trim failed, using CPU: %s", r.stderr.decode(errors="replace")[-200:])
            r = subprocess.run(self._encode_cmd(src, start, end, out, "libx264", wm), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=900, creationflags=NO_WINDOW)
        if r.returncode != 0 or not os.path.exists(out):
            raise ExportError("Couldn't prepare the clip: " + r.stderr.decode(errors="replace").strip()[-200:])
        return {"path": out, "duration": round(probe_duration(self.ff, out) or (end - start), 2),
                "size": os.path.getsize(out)}

    def _encode_cmd(self, src, start, end, out, encoder, wm=False):
        cmd = [self.ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-i", src]
        if wm:
            import watermark
            cmd += watermark.inputs(watermark.png_for(probe_height(self.ff, src)))
            cmd += ["-t", f"{end - start:.3f}", "-filter_complex", watermark.filter_graph(),
                    "-map", "[vo]", "-map", "0:a?", "-c:v", encoder]
        else:
            cmd += ["-t", f"{end - start:.3f}", "-map", "0:v:0", "-map", "0:a?", "-c:v", encoder]
        if "nvenc" in encoder:
            cmd += ["-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]
        elif "amf" in encoder:
            cmd += ["-quality", "quality", "-rc", "cqp", "-qp_i", "20", "-qp_p", "22"]
        elif "qsv" in encoder:
            cmd += ["-global_quality", "21"]
        else:
            cmd += ["-preset", "veryfast", "-crf", "20"]
        return cmd + ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]

    def add_watermark(self, clip_id, encoder):
        """Burns "Clipped by Verse Platform" into the first 2 seconds of a saved clip, in place.
        Runs at low priority. Keeps the original if anything goes wrong."""
        clip = self.get(clip_id)
        if not clip or clip.get("watermarked"):
            return False
        src = self.abs_path(clip)
        dur = clip.get("duration") or probe_duration(self.ff, src)
        if not dur:
            return False
        tmp = src + ".wm.mp4"
        ok = False
        for enc in ([encoder, "libx264"] if encoder != "libx264" else ["libx264"]):
            cmd = self._encode_cmd(src, 0, dur, tmp, enc, wm=True)
            # keep the original audio as is (no re-encode)
            i = cmd.index("-c:a")
            cmd[i + 1:i + 4] = ["copy"]
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800,
                               creationflags=NO_WINDOW | LOW_PRIORITY)
            if r.returncode == 0 and os.path.exists(tmp) and probe_duration(self.ff, tmp) > dur - 1:
                ok = True
                break
            log.warning("Watermark with %s failed: %s", enc, r.stderr.decode(errors="replace")[-300:])
        if not ok:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        for _ in range(20):  # the player may have the file open for a moment
            try:
                os.replace(tmp, src)
                break
            except OSError:
                time.sleep(1)
        else:
            log.warning("Couldn't swap in the watermarked clip, keeping the original")
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        with self.lock:
            if clip_id in self.clips:
                self.clips[clip_id]["watermarked"] = True
                self.clips[clip_id]["size"] = os.path.getsize(src)
                self._save()
        return True

    def set_folder(self, folder):
        with self.lock:
            self.clips_folder = folder


# --------------------------------------------------------------------------- local media server

class MediaServer:
    """Serves clips and thumbnails to the app window on 127.0.0.1 only, behind a random
    secret path. Supports Range requests so the video player can seek."""

    def __init__(self, library, ui_dir="", on_command=None):
        self.library = library
        self.secret = secrets.token_urlsafe(16)
        lib, secret = library, self.secret
        ui_root = os.path.realpath(ui_dir) if ui_dir else ""
        types = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript",
                 ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".ico": "image/x-icon"}

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _cors(self):
                # only verseplatform.gg may read clips, and only through the secret URL the app hands it
                origin = self.headers.get("Origin", "")
                if origin in ALLOWED_ORIGINS:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Private-Network", "true")
                    self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range")

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Range")
                self.send_header("Access-Control-Max-Age", "600")
                self.end_headers()

            def do_GET(self):
                parts = urllib.parse.unquote(urllib.parse.urlparse(self.path).path).strip("/").split("/", 2)
                if len(parts) < 2 or parts[0] != secret:
                    return self.send_error(404)
                if parts[1] == "show" and on_command:  # a second copy was launched: bring the window up
                    on_command("show")
                    self.send_response(204)
                    self.end_headers()
                    return
                if parts[1] == "ui" and ui_root and len(parts) == 3:
                    path = os.path.realpath(os.path.join(ui_root, parts[2]))
                    if not path.startswith(ui_root + os.sep) or not os.path.isfile(path):
                        return self.send_error(404)
                    with open(path, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", types.get(os.path.splitext(path)[1].lower(), "application/octet-stream"))
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if len(parts) != 3:
                    return self.send_error(404)
                clip = lib.get(parts[2].split(".")[0])
                if not clip:
                    return self.send_error(404)
                if parts[1] == "clip":
                    path, ctype = lib.abs_path(clip), "video/mp4"
                elif parts[1] == "export":
                    path, ctype = lib.export_path(clip["id"]), "video/mp4"
                elif parts[1] == "thumb":
                    path, ctype = lib.thumb_path(clip), "image/jpeg"
                else:
                    return self.send_error(404)
                if not path or not os.path.exists(path):
                    return self.send_error(404)
                size = os.path.getsize(path)
                start, end = 0, size - 1
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    a, _, b = rng[6:].split(",")[0].partition("-")
                    if a:
                        start = int(a)
                        end = int(b) if b else end
                    else:
                        start = max(0, size - int(b))
                    end = min(end, size - 1)
                    if start > end:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                self._cors()
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Cache-Control", "no-store" if ctype == "video/mp4" else "max-age=3600")
                self.end_headers()
                try:
                    with open(path, "rb") as f:
                        f.seek(start)
                        left = end - start + 1
                        while left > 0:
                            chunk = f.read(min(512 * 1024, left))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            left -= len(chunk)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True

        self.httpd = Server(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, kind, clip_id=""):
        return f"http://127.0.0.1:{self.port}/{self.secret}/{kind}/{clip_id}"

