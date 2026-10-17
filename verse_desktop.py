"""
Verse Platform for Windows.

  * the window shows the real Verse website (verseplatform.gg), so the feed, profiles,
    messages, game tags and the Upload screen are always the live ones
  * on top of that, the desktop extras: game capture with a save-clip hotkey, a clip
    library on this PC (preview + trim), and Publish, which hands a clip to Verse's
    own Upload screen
  * clips stay on the PC. Nothing is uploaded unless the player publishes it
  * a tray icon keeps recording when the window is closed

Run with --background to start hidden in the tray (used by "Start with Windows").
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.parse

from rewind_core import (APP_NAME, APP_VERSION, DATA_DIR, IS_WINDOWS, KNOWN_GAMES, LOG_PATH, NOT_GAMES, RES,
                         SEGMENT_SECONDS, VERSE_URL, GameWatcher, Recorder, already_running, find_ffmpeg,
                         get_autostart, list_mics, load_config, load_icon_image, message_box, open_path,
                         save_config, set_autostart, visible_windows, _size)
from library import ALLOWED_ORIGINS, ClipLibrary, ExportError, MediaServer
from updater import Updater
from overlay import Overlay, secs_text
from highlights import DEFAULT_EVENTS, LeagueHighlights

log = logging.getLogger(APP_NAME)
INSTANCE_FILE = os.path.join(DATA_DIR, "instance.json")

# settings that need capture restarted to take effect
RESTART_KEYS = {"fps", "bitrate", "output_height", "monitor", "record_desktop_audio", "mic_device",
                "encoder", "capture", "draw_mouse", "audio_offset_ms"}
LIVE_KEYS = {"hotkey", "buffer_seconds", "record_mode", "detect_fullscreen_apps", "stop_delay_seconds",
             "custom_games", "ignored_apps", "play_sound_on_save", "sort_clips_by_game",
             "show_save_overlay", "auto_highlights", "highlight_events", "highlight_before",
             "highlight_after", "highlight_max_per_game"}

# A small "Clips" tab added to the left edge of Verse pages inside the app, so the clip library
# is always one click away. Verse can render its own button instead: if the page has an element
# with id "verse-desktop-nav", this tab stays hidden.
DOCK_JS = r"""
(function () {
  if (window.__verseDock) return;
  window.__verseDock = true;
  function ready(fn) {
    if (window.pywebview && window.pywebview.api) fn();
    else window.addEventListener('pywebviewready', fn, { once: true });
  }
  ready(function () {
    var css = document.createElement('style');
    css.textContent =
      '#vp-dock{position:fixed;left:0;top:50%;transform:translateY(-50%);z-index:2147483000;display:flex;' +
      'flex-direction:column;align-items:center;gap:8px;padding:12px 7px;background:rgba(10,10,10,.92);' +
      'border:1px solid #262626;border-left:0;border-radius:0 14px 14px 0;cursor:pointer;color:#fafafa;' +
      'font:600 11px/1 system-ui,-apple-system,Segoe UI,sans-serif;letter-spacing:.08em;' +
      'box-shadow:0 6px 24px rgba(0,0,0,.5);transition:background .15s}' +
      '#vp-dock:hover{background:#111;border-color:#06b6d4}' +
      '#vp-dock .d{width:9px;height:9px;border-radius:50%;background:#404040}' +
      '#vp-dock.rec .d{background:#ef4444;box-shadow:0 0 0 3px rgba(239,68,68,.25)}' +
      '#vp-dock .t{writing-mode:vertical-rl;transform:rotate(180deg)}' +
      '#vp-dock .n{min-width:18px;padding:3px 5px;border-radius:999px;background:#06b6d4;color:#000;text-align:center}';
    document.head.appendChild(css);
    var d = document.createElement('div');
    d.id = 'vp-dock';
    d.title = 'Your clips on this PC';
    d.innerHTML = '<span class="d"></span><span class="t">CLIPS</span><span class="n">0</span>';
    d.onclick = function () { window.pywebview.api.open_library(); };
    document.body.appendChild(d);
    function tick() {
      // hide this tab only while Verse's own My clips button is actually on screen
      var nav = document.getElementById('verse-desktop-nav'), r = nav && nav.getBoundingClientRect();
      var shown = r && r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight &&
                  getComputedStyle(nav).visibility !== 'hidden';
      d.style.display = shown ? 'none' : 'flex';
      if (shown) return;
      window.pywebview.api.dock_state().then(function (s) {
        if (!s) return;
        d.classList.toggle('rec', !!s.capturing);
        d.title = s.title + ' - ' + s.clips + ' clip' + (s.clips === 1 ? '' : 's') + ' on this PC';
        d.querySelector('.n').textContent = s.clips;
      }).catch(function () {});
    }
    tick();
    setInterval(tick, 1500);
  });
})();
"""


def pretty_hotkey(h):
    return h.upper().replace("+", " + ")


def length_text(sec):
    return f"{sec // 60} min" if sec % 60 == 0 else f"{sec} seconds"


def origin_of(url):
    p = urllib.parse.urlparse(url or "")
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""


class App:
    def __init__(self, ff, background):
        self.ff = ff
        self.background = background
        self.cfg = load_config()
        self.rec = None
        self.title, self.subtitle = "Starting up", "Getting capture ready"
        self.quitting = False
        self.notices = []
        self.mics = []
        self.window = None
        self.win_hidden = background   # closed to the tray
        self.win_minimized = False
        self.icon = None
        self.clips_rev = 0
        self.lock = threading.RLock()

        self.watcher = GameWatcher(lambda: self.cfg)
        self.library = ClipLibrary(self.cfg["clips_folder"], DATA_DIR, ff)
        self.media = MediaServer(self.library, os.path.join(RES, "ui"), self.on_command)
        self.updater = Updater(self.on_update_ready)
        self.overlay = Overlay(lambda: self.cfg.get("monitor", 0))
        self.highlights = LeagueHighlights(lambda: self.cfg, self.is_playing, self.save_highlight)
        try:
            with open(INSTANCE_FILE, "w", encoding="utf-8") as f:
                json.dump({"port": self.media.port, "secret": self.media.secret}, f)
        except OSError:
            pass

    # ------------------------------------------------------------ small helpers
    @property
    def verse(self):
        return (self.cfg.get("verse_url") or VERSE_URL).rstrip("/")

    def library_url(self):
        return self.media.url("ui", "index.html")

    def current_url(self):
        try:
            return self.window.get_current_url() or ""
        except Exception:
            return ""

    def on_verse(self, url=None):
        o = origin_of(url if url is not None else self.current_url())
        return o in ALLOWED_ORIGINS or o == origin_of(self.verse)

    def on_library(self, url=None):
        return (url if url is not None else self.current_url()).startswith(f"http://127.0.0.1:{self.media.port}/")

    def bump(self):
        self.clips_rev += 1

    def notice(self, text):
        self.notices.append(text)

    def notify(self, title, text):
        """Windows notification from the tray icon."""
        try:
            if self.icon:
                self.icon.notify(text, title)
        except Exception:
            pass

    def on_command(self, cmd):
        if cmd == "show":
            self.show_window()

    def show_window(self, *_):
        """Bring the window back only if it's hidden or minimized. Never touch its size,
        so a maximized window stays maximized."""
        if not self.window:
            return
        if self.win_hidden:
            self.window.show()
            self.win_hidden = False
        if self.win_minimized:
            self.window.restore()
            self.win_minimized = False

    def open_library(self, *_):
        if self.window:
            self.window.load_url(self.library_url())
            self.show_window()

    def open_verse(self, path="/Home"):
        if self.window:
            path = path if str(path).startswith("/") else "/" + str(path)
            self.window.load_url(self.verse + path)
            self.show_window()

    # ------------------------------------------------------------ recording
    def start_recorder(self):
        with self.lock:
            if self.rec:
                self.rec.stop()
                self.rec = None
            rec = Recorder(self.cfg, self.ff)
            rec.on_saved = self.on_saved
            rec.start(capture=False)  # the watch loop decides when to actually record
            self.rec = rec
        self.register_hotkey()

    def register_hotkey(self):
        import keyboard
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        try:
            keyboard.add_hotkey(self.cfg["hotkey"], self.save_clip_async)
            return True
        except Exception as e:
            log.error("Bad hotkey %r: %s", self.cfg["hotkey"], e)
            self.notice(f"The shortcut {pretty_hotkey(self.cfg['hotkey'])} can't be used, pick another")
            return False

    def save_clip_async(self, *_):
        if self.rec:
            threading.Thread(target=self.rec.save_clip, daemon=True).start()

    def is_playing(self, game):
        return bool(self.rec and self.rec.capturing and self.rec.label == game)

    def save_highlight(self, label, start, end):
        if self.rec and (self.rec.capturing or self.rec.segments()):
            self.rec.save_clip(tag=label, window=(start, end))

    def on_saved(self, path, msg):
        if self.cfg.get("play_sound_on_save") and IS_WINDOWS:
            import winsound
            winsound.MessageBeep(winsound.MB_OK if path else winsound.MB_ICONHAND)
        overlay = self.cfg.get("show_save_overlay", True)
        if not path:
            self.notice(msg)
            if overlay:
                self.overlay.show(msg, accent="", ok=False)
            self.notify(APP_NAME, msg)
            return
        game = self.rec.label if self.rec else ""
        tag = getattr(self.rec, "last_tag", "") if self.rec else ""
        secs = secs_text(getattr(self.rec, "last_seconds", 0) or self.cfg["buffer_seconds"])
        self.library.add(path, game=game, highlight=tag)
        self.bump()
        if tag:
            self.notice(f"Highlight saved: {tag}")
            if overlay:
                self.overlay.show(tag, accent="", sub=f"{game}  \u00b7  last {secs} saved by Verse Platform")
            else:
                self.notify(f"Highlight saved: {tag}", f"{game} clip saved on this PC.")
            return
        self.notice("Clip saved to your library")
        if overlay:
            self.overlay.show(f"Last {secs} saved by")
        else:
            self.notify("Clip saved", f"{game or 'Clip'} saved on this PC. Open Clips to post it to Verse.")

    def watch_loop(self):
        """Every 2 seconds: is a game running? Start or stop recording to match."""
        last_seen = 0.0
        while not self.quitting:
            rec, c = self.rec, self.cfg
            now = time.time()
            hk = pretty_hotkey(c["hotkey"])
            try:
                if rec and rec.running:
                    if c.get("record_mode") == "always":
                        if not rec.capturing:
                            rec.begin_capture("")
                        rec.label = ""
                        self.title = "Recording"
                        self.subtitle = f"Always on. Press {hk} to save the last {length_text(c['buffer_seconds'])}"
                    else:
                        game = self.watcher.detect()
                        if game:
                            last_seen = now
                            if not rec.capturing:
                                rec.begin_capture(game)
                                self.notify(f"Recording {game}", f"Press {hk} to save a clip")
                            rec.label = game
                            self.title = game
                            self.subtitle = f"Recording. Press {hk} to save the last {length_text(c['buffer_seconds'])}"
                        elif rec.capturing:
                            if now - last_seen > c.get("stop_delay_seconds", 20):
                                rec.end_capture()
                            else:
                                self.title = rec.label or "Recording"
                                self.subtitle = "Game closed. Recording stops in a moment"
                        if not rec.capturing:
                            self.title = "Waiting for a game"
                            self.subtitle = (f"Game ended. {hk} still saves its last moments" if rec.segments()
                                             else "Recording starts by itself when a game opens")
            except Exception:
                log.exception("Game detection hiccup")
            if self.icon:
                try:
                    self.icon.title = f"{APP_NAME}: {self.title}"[:120]
                except Exception:
                    pass
            time.sleep(2)

    def buffered_seconds(self):
        rec = self.rec
        if not rec:
            return 0
        n = sum(1 for s in rec.segments() if _size(s) > 4096)
        return min(self.cfg["buffer_seconds"], n * SEGMENT_SECONDS)

    # ------------------------------------------------------------ window events
    def on_loaded(self):
        """Every page load: add the Clips tab to Verse pages."""
        url = self.current_url()
        if self.on_verse(url):
            try:
                self.window.evaluate_js(DOCK_JS)
            except Exception:
                log.debug("dock inject failed", exc_info=True)

    # ------------------------------------------------------------ startup / shutdown
    def boot(self):
        """Slow startup work, off the UI thread."""
        try:
            self.start_recorder()
        except Exception as e:
            log.exception("Could not start recording")
            self.title, self.subtitle = "Not recording", "Capture couldn't start. The log has details"
            message_box(f"Recording couldn't start:\n{e}\n\nDetails are in {LOG_PATH}", error=True)
        threading.Thread(target=self.watch_loop, daemon=True).start()
        threading.Thread(target=self._scan_library, daemon=True).start()
        self.mics = list_mics(self.ff) if IS_WINDOWS else []
        self.updater.start()
        self.highlights.start()

    # ------------------------------------------------------------ updates
    def on_update_ready(self, version):
        idle = not (self.rec and self.rec.capturing) and self.win_hidden
        if idle:
            # nobody is playing or looking at the window (e.g. just after Windows started): update now
            self.update_now(relaunch_hidden=True)
            return
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass
        self.notify(f"Update {version} is ready", "Click Update now in the tray or My clips. It also installs when you quit.")
        self.bump()

    def update_now(self, relaunch_hidden=False):
        if self.rec and self.rec.capturing and not relaunch_hidden:
            self.notices.append("Finish your game first. The update installs when you quit, or try again later.")
            return False
        if self.updater.install(relaunch=True, background=relaunch_hidden):
            self.quit()
            return True
        return False

    def _scan_library(self):
        try:
            self.library.scan()
            self.bump()
        except Exception:
            log.exception("Library scan failed")

    def quit(self, *_):
        if self.quitting:
            return
        self.quitting = True
        if self.updater.version and not self.updater.installing:
            self.updater.install(relaunch=False)  # pending update goes in quietly on the way out
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        if self.rec:
            self.rec.stop()
        try:
            os.remove(INSTANCE_FILE)
        except OSError:
            pass
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass


class Api:
    """Everything JavaScript in the window can call (window.pywebview.api.*).

    Two kinds of page live in the window:
      * the clip library and settings (served by the app itself on 127.0.0.1)
      * verseplatform.gg, which can ask for a clip the player chose to publish
    Calls from any other website are refused.
    """

    def __init__(self, app):
        self._app = app

    def _from_library(self):
        return self._app.on_library()

    def _from_trusted(self):
        return self._app.on_library() or self._app.on_verse()

    # ================================================================ called by Verse pages
    def desktop_info(self):
        """Lets Verse know it's running inside the desktop app."""
        if not self._from_trusted():
            return None
        a = self._app
        return {"app": APP_NAME, "version": APP_VERSION, "platform": "windows",
                "hotkey": a.cfg["hotkey"], "capturing": bool(a.rec and a.rec.capturing)}

    def dock_state(self):
        if not self._from_trusted():
            return None
        a = self._app
        return {"capturing": bool(a.rec and a.rec.capturing), "title": a.title,
                "clips": sum(1 for _ in a.library.list())}

    def open_library(self):
        if not self._from_trusted():
            return None
        threading.Timer(0.05, self._app.open_library).start()
        return True

    def get_clip(self, clip_id):
        """Verse's Upload screen calls this with the id from ?desktopClip=... and gets back
        a URL it can fetch the video from (only verseplatform.gg is allowed to read it)."""
        if not self._from_trusted():
            return None
        a = self._app
        clip = a.library.get(str(clip_id))
        if not clip:
            return {"error": "That clip isn't on this PC any more"}
        path = a.library.export_path(clip["id"])
        kind = "export" if os.path.exists(path) else "clip"
        if kind == "clip":
            path = a.library.abs_path(clip)
        return {
            "id": clip["id"],
            "url": a.media.url(kind, clip["id"]) + ".mp4",
            "file_name": f"{clip.get('title') or 'Clip'}.mp4".replace("/", "-").replace("\\", "-"),
            "mime_type": "video/mp4",
            "size": os.path.getsize(path) if os.path.exists(path) else 0,
            "duration_seconds": clip.get("export_duration") or clip.get("duration", 0),
            "title": clip.get("title", ""),
            "game": clip.get("game", ""),
            "recorded_at": clip.get("created", ""),
            "thumbnail_url": a.media.url("thumb", clip["id"]) if clip.get("thumb") else "",
        }

    def clip_published(self, clip_id, url=""):
        """Verse calls this after the post is live, so the library can show it as posted."""
        if not self._from_trusted():
            return None
        a = self._app
        a.library.mark_posted(str(clip_id), str(url or ""))
        try:
            os.remove(a.library.export_path(str(clip_id)))
        except OSError:
            pass
        a.bump()
        a.notify("Posted to Verse", "Your clip is live")
        return True

    def save_clip(self):
        if not self._from_trusted():
            return None
        a = self._app
        if not a.rec:
            return {"message": "Capture isn't running"}
        if not a.rec.capturing and not a.rec.segments():
            return {"message": "Nothing to save yet. Recording starts when a game opens"}
        a.save_clip_async()
        return {"message": "Saving clip..."}

    # ================================================================ called by the clip library
    def get_state(self):
        if not self._from_library():
            return None
        a = self._app
        return {
            "title": a.title,
            "subtitle": a.subtitle,
            "capturing": bool(a.rec and a.rec.capturing),
            "buffer_seconds": a.cfg["buffer_seconds"],
            "buffered_seconds": a.buffered_seconds(),
            "hotkey": a.cfg["hotkey"],
            "max_post_seconds": a.cfg.get("max_post_seconds", 60),
            "clips_rev": a.clips_rev,
            "notice": a.notices.pop(0) if a.notices else "",
            "update": a.updater.version,
        }

    def update_now(self):
        if not self._from_library():
            return None
        return {"ok": self._app.update_now()}

    def list_clips(self):
        if not self._from_library():
            return None
        a = self._app
        out = []
        for c in a.library.list():
            c["thumb_url"] = a.media.url("thumb", c["id"]) if c.get("thumb") else ""
            c["video_url"] = a.media.url("clip", c["id"])
            out.append(c)
        return out

    def rename_clip(self, clip_id, title):
        if self._from_library():
            self._app.library.rename(clip_id, title)
            self._app.bump()

    def delete_clip(self, clip_id):
        if self._from_library():
            self._app.library.delete(clip_id)
            self._app.bump()

    def show_in_folder(self, clip_id):
        if not self._from_library():
            return
        c = self._app.library.get(clip_id)
        if c and IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self._app.library.abs_path(c))])

    def open_clips_folder(self):
        if self._from_library():
            os.makedirs(self._app.cfg["clips_folder"], exist_ok=True)
            open_path(self._app.cfg["clips_folder"])

    def go_verse(self, path="/Home"):
        if self._from_library():
            threading.Timer(0.05, self._app.open_verse, args=(path,)).start()

    def publish_clip(self, clip_id, start, end):
        """Makes the trimmed copy, then opens Verse's Upload screen with the clip handed over."""
        if not self._from_library():
            return None
        a = self._app
        try:
            info = a.library.export(clip_id, start, end, a.rec.encoder if a.rec else "libx264",
                                    a.cfg.get("max_post_seconds", 60))
        except ExportError as e:
            return {"error": str(e)}
        except Exception as e:
            log.exception("Export failed")
            return {"error": f"Couldn't prepare the clip ({e})"}
        with a.library.lock:
            if clip_id in a.library.clips:
                a.library.clips[clip_id]["export_duration"] = info["duration"]
        threading.Timer(0.05, a.open_verse, args=(f"/Upload?desktopClip={urllib.parse.quote(clip_id)}",)).start()
        return {"ok": True}

    # ---- settings
    def get_settings(self):
        if not self._from_library():
            return None
        a = self._app
        known = set(a.watcher.games())
        custom = {k.lower() for k in a.cfg.get("custom_games", {})}
        running, seen = [], set()
        for w in (visible_windows() if IS_WINDOWS else []):
            if not w.exe or w.exe in NOT_GAMES or w.exe in known or w.exe in custom or w.exe in seen:
                continue
            seen.add(w.exe)
            running.append({"exe": w.exe, "name": w.title.strip()[:40] or os.path.splitext(w.exe)[0]})
        return {
            "config": a.cfg,
            "mics": a.mics,
            "autostart": get_autostart(),
            "known_games": sorted(set(KNOWN_GAMES.values())),
            "running_apps": running,
            "version": APP_VERSION,
            "highlight_defaults": DEFAULT_EVENTS,
        }

    def set_setting(self, key, value):
        if not self._from_library():
            return None
        a = self._app
        if key not in RESTART_KEYS and key not in LIVE_KEYS:
            return {"message": "Unknown setting"}
        old = a.cfg.get(key)
        a.cfg[key] = value
        if key == "hotkey" and not a.register_hotkey():
            a.cfg[key] = old
            a.register_hotkey()
            return {"message": "That shortcut can't be used, try another"}
        save_config(a.cfg)
        if key in RESTART_KEYS:
            threading.Thread(target=a.start_recorder, daemon=True).start()
            return {"message": "Saved. Recording restarted with the new setting"}
        if key == "hotkey":
            return {"message": f"Shortcut is now {pretty_hotkey(value)}"}
        return {}

    def set_autostart(self, on):
        if self._from_library():
            set_autostart(bool(on))

    def add_game(self, exe, name):
        if not self._from_library():
            return None
        games = dict(self._app.cfg.get("custom_games", {}))
        games[exe] = name
        self._app.cfg["ignored_apps"] = [x for x in self._app.cfg.get("ignored_apps", []) if x.lower() != exe.lower()]
        return self.set_setting("custom_games", games)

    def remove_game(self, exe):
        if not self._from_library():
            return None
        games = {k: v for k, v in self._app.cfg.get("custom_games", {}).items() if k != exe}
        return self.set_setting("custom_games", games)

    def choose_clips_folder(self):
        if not self._from_library():
            return None
        import webview
        a = self._app
        res = a.window.create_file_dialog(webview.FOLDER_DIALOG, directory=a.cfg["clips_folder"])
        if not res:
            return {}
        folder = res[0] if isinstance(res, (list, tuple)) else res
        a.cfg["clips_folder"] = folder
        save_config(a.cfg)
        a.library.set_folder(folder)
        threading.Thread(target=a._scan_library, daemon=True).start()
        threading.Thread(target=a.start_recorder, daemon=True).start()
        return {"message": "Clips folder changed"}


# ------------------------------------------------------------------ tray + window

def main():
    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stderr:  # the windowed .exe has no console to print to
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    log.info("%s %s starting", APP_NAME, APP_VERSION)
    background = "--background" in sys.argv

    if already_running():
        # bring the running copy's window to the front instead of starting a second one
        try:
            import urllib.request
            with open(INSTANCE_FILE, encoding="utf-8") as f:
                inst = json.load(f)
            urllib.request.urlopen(f"http://127.0.0.1:{inst['port']}/{inst['secret']}/show", timeout=3)
        except Exception:
            if not background:
                message_box(f"{APP_NAME} is already running. Look for its icon in the system tray.")
        return
    if IS_WINDOWS:
        try:  # real pixel sizes, so fullscreen detection works with display scaling
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

    cfg = load_config()
    try:
        ff = find_ffmpeg(cfg)
    except RuntimeError as e:
        log.error(str(e))
        message_box(str(e), error=True)
        sys.exit(1)

    import pystray
    import webview

    app = App(ff, background)
    api = Api(app)

    app.icon = pystray.Icon("VersePlatform", load_icon_image(), APP_NAME, menu=pystray.Menu(
        pystray.MenuItem("Open Verse", lambda *_: app.open_verse("/Home"), default=True),
        pystray.MenuItem("My clips", app.open_library),
        pystray.MenuItem(lambda i: f"Save clip  ({pretty_hotkey(app.cfg['hotkey'])})", lambda *_: app.save_clip_async()),
        pystray.MenuItem(lambda i: f"Update now  (to {app.updater.version})", lambda *_: app.update_now(),
                         visible=lambda i: bool(app.updater.version)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Quit {APP_NAME}", app.quit),
    ))
    threading.Thread(target=app.icon.run, daemon=True).start()

    # links that leave Verse (Discord, YouTube...) open in the normal browser
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    app.window = webview.create_window(
        APP_NAME, app.verse + "/Home", js_api=api,
        width=1360, height=860, min_size=(960, 640), background_color="#0A0A0A", hidden=background)

    def on_closing():
        if app.quitting:
            return True
        app.win_hidden = True
        threading.Timer(0.05, app.window.hide).start()  # closing the window keeps recording in the tray
        if not getattr(app, "_told_tray", False):
            app._told_tray = True
            app.notify(APP_NAME, "Still recording in the background. Find Verse in the system tray.")
        return False

    app.window.events.closing += on_closing
    app.window.events.loaded += app.on_loaded

    def on_minimized():
        app.win_minimized = True

    def on_restored():
        app.win_minimized = False

    app.window.events.minimized += on_minimized
    app.window.events.restored += on_restored
    app.window.events.maximized += on_restored
    app.window.events.shown += lambda: setattr(app, "win_hidden", False)
    threading.Thread(target=app.boot, daemon=True).start()
    webview.start(gui="edgechromium" if IS_WINDOWS else None, private_mode=False,
                  storage_path=os.path.join(DATA_DIR, "webview"))
    app.quit()


if __name__ == "__main__":
    main()
