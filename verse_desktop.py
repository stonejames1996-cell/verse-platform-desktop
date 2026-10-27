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
import queue
import subprocess
import sys
import threading
import time
import urllib.parse

from rewind_core import (APP_NAME, APP_VERSION, DATA_DIR, IS_WINDOWS, KNOWN_GAMES, LOG_PATH, NOT_GAMES, RES,
                         SEGMENT_SECONDS, VERSE_URL, GameWatcher, Recorder, already_running, find_ffmpeg,
                         get_autostart, list_mics, load_config, load_icon_image, message_box, open_path,
                         save_config, screen_rect, set_autostart, visible_windows, _size)
from library import ALLOWED_ORIGINS, ClipLibrary, ExportError, MediaServer
from updater import Updater
from overlay import Overlay, secs_text
from highlights import DEFAULT_EVENTS, LeagueHighlights
from lol_live import LeagueCompanion
from triggers import COMBOS, ControllerTrigger, VoiceTrigger
from gsi import CS2Highlights, DotaHighlights, GSIServer, install_cfgs
from squad import Squad, make_code
from library import highlight_score

log = logging.getLogger(APP_NAME)
INSTANCE_FILE = os.path.join(DATA_DIR, "instance.json")

# settings that need capture restarted to take effect
RESTART_KEYS = {"fps", "bitrate", "output_height", "monitor", "record_desktop_audio", "mic_device",
                "encoder", "capture", "draw_mouse", "audio_offset_ms"}
LIVE_KEYS = {"hotkey", "buffer_seconds", "record_mode", "detect_fullscreen_apps", "stop_delay_seconds",
             "custom_games", "ignored_apps", "play_sound_on_save", "sort_clips_by_game",
             "show_save_overlay", "auto_highlights", "highlight_events", "highlight_before",
             "highlight_after", "highlight_max_per_game", "voice_command",
             "death_review", "death_review_before", "squad_code", "squad_name", "squad_share",
             "controller_combo", "auto_clean_days", "auto_clean_permanent", "follow_game_screen",
             "lol_item_ideas", "lol_objective_timers", "lol_match_summary",
             "lol_benchmarks", "lol_opgg"}

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
    // "What's new" card after an update, shown once the window is in front
    var wnAsked = false;
    function whatsNew() {
      if (wnAsked || !document.hasFocus()) return;
      wnAsked = true;
      window.pywebview.api.whats_new().then(function (w) {
        if (!w || !w.notes || !w.notes.length) return;
        var host = document.createElement('div');
        host.style.cssText = 'position:fixed;inset:0;z-index:2147483600';
        var root = host.attachShadow({ mode: 'open' });
        var items = w.notes.map(function (n, i) {
          return '<section><h3>' + (i ? 'Version ' + n.version : "What's new in " + n.version) + '</h3>' + n.html + '</section>';
        }).join('');
        root.innerHTML = '<style>' +
          '.bg{position:fixed;inset:0;background:rgba(0,0,0,.6);display:grid;place-items:center;padding:16px;font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:#fafafa}' +
          '.box{width:min(520px,100%);max-height:min(640px,90vh);display:flex;flex-direction:column;background:#111;border:1px solid #262626;border-radius:16px;box-shadow:0 24px 70px rgba(0,0,0,.6);overflow:hidden}' +
          '.top{display:flex;align-items:center;gap:12px;padding:20px 22px 6px}.top b{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#22d3ee}' +
          '.body{overflow:auto;padding:4px 22px 6px}h3{font-size:19px;margin:12px 0 6px}section+section h3{font-size:15px;color:#a3a3a3;margin-top:18px}' +
          'ul{margin:0;padding-left:20px}li{margin:6px 0}strong{color:#fff}code{background:#1f1f1f;padding:1px 5px;border-radius:5px;font-size:12.5px}p{margin:6px 0;color:#d4d4d4}' +
          '.foot{display:flex;justify-content:flex-end;padding:14px 22px 18px}button{background:#06b6d4;color:#000;border:0;border-radius:999px;padding:9px 22px;font:600 14px system-ui,Segoe UI,sans-serif;cursor:pointer}button:hover{background:#22d3ee}' +
          '</style><div class="bg" role="dialog" aria-modal="true" aria-label="What\'s new"><div class="box"><div class="top"><b>Verse Platform updated</b></div>' +
          '<div class="body">' + items + '</div><div class="foot"><button>Got it</button></div></div></div>';
        function close() { host.remove(); window.pywebview.api.whats_new_seen(); document.removeEventListener('keydown', key, true); }
        function key(e) { if (e.key === 'Escape' || e.key === 'Enter') close(); }
        root.querySelector('button').onclick = close;
        root.querySelector('.bg').onclick = function (e) { if (e.target === e.currentTarget) close(); };
        document.addEventListener('keydown', key, true);
        document.body.appendChild(host);
        root.querySelector('button').focus();
      }).catch(function () { wnAsked = false; });
    }
    tick();
    setInterval(function () { tick(); whatsNew(); }, 1500);
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


_crash_file = None

GAME_TAGS = {"League of Legends": "leagueoflegends", "VALORANT": "valorant", "Counter-Strike 2": "cs2", "CS2": "cs2",
             "Fortnite": "fortnite", "Apex Legends": "apexlegends", "Overwatch 2": "overwatch2",
             "Rocket League": "rocketleague", "Minecraft": "minecraft", "Marvel Rivals": "marvelrivals"}


def _tag(text):
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def caption_info(clip, match):
    """A ready-made caption and hashtags from what the app knows about the clip, for Verse's Upload
    screen to pre-fill (and to give its AI caption writer context)."""
    match = match or {}
    game, hl = clip.get("game") or "", clip.get("highlight") or ""
    champ, mode = match.get("champion") or "", match.get("mode") or ""
    if clip.get("recap"):
        text = f"My week{' in ' + game if game else ''} 🎬"
    elif hl:
        text = hl + (f" on {champ}" if champ else "") + (f" in {mode}" if mode and mode not in ("Summoner's Rift", "Dota") else "")
        text += " 🔥" if highlight_score(hl) >= 5 else " 🎮"
    elif champ:
        text = f"{champ} in {mode or game} 🎮"
    else:
        text = f"{game} clip 🎮" if game else ""
    tags = [GAME_TAGS.get(game) or _tag(game)]
    tags += [_tag(p) for p in hl.split(" + ")] if hl else []
    tags += [_tag(champ), _tag(mode) if mode and mode not in ("Summoner's Rift", "Dota") else ""]
    tags += ["weeklyrecap"] if clip.get("recap") else []
    tags += ["vertical"] if clip.get("vertical") else []
    tags = [t for i, t in enumerate(tags) if t and t not in tags[:i]] + ["verse"]
    out = {"suggested_caption": text, "suggested_hashtags": tags, "highlight": hl,
           "is_recap": bool(clip.get("recap")), "is_vertical": bool(clip.get("vertical"))}
    if match:
        out["match"] = {k: match.get(k) for k in ("mode", "champion", "result", "kills", "deaths", "assists", "length")}
    return out


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
        self.overlay = Overlay(self.popup_screen)
        self.wm_queue = queue.Queue()
        threading.Thread(target=self._watermark_loop, daemon=True, name="watermark").start()
        self.current_match = None
        self.voice = VoiceTrigger(self.trigger_save)
        self.pad = ControllerTrigger(lambda: self.cfg.get("controller_combo", ""), self.trigger_save)
        # League: objective timers, the panel while you're dead (stats, lane gold, item ideas), match summary
        self.timer_strip = Overlay(self.popup_screen, name="VersePlatformTimers")
        self.item_ideas = LeagueCompanion(
            lambda: self.cfg, self.is_playing, self.overlay, self.timer_strip, DATA_DIR,
            get_match=lambda: self.highlights.match, on_summary=self.on_match_summary, notify=self.notify,
            count_clips=lambda mid: sum(1 for c in self.library.list() if mid and c.get("match") == mid
                                        and c.get("highlight") and not c.get("review")))
        self.highlights = LeagueHighlights(lambda: self.cfg, self.is_playing, self.save_highlight,
                                           on_match=self.on_match, on_death=self.on_death)
        # auto clips, death reviews and squad clips queue up here, so two at once never collide
        self.save_q = queue.Queue()
        threading.Thread(target=self._save_loop, daemon=True, name="saves").start()
        self.gsi_games = {
            "cs2": CS2Highlights(lambda: self.cfg, self.is_playing, self.save_highlight,
                                 on_match=self.on_match, on_death=self.on_death),
            "dota2": DotaHighlights(lambda: self.cfg, self.is_playing, self.save_highlight,
                                    on_match=self.on_match, on_death=self.on_death),
        }
        self.gsi_setup = {}
        self.squad = Squad(self)
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

    # ------------------------------------------------------------ sign-in pop-up (Link Xbox)
    SIGN_IN_HOSTS = {"login.microsoftonline.com", "login.live.com"}

    def open_sign_in(self, url):
        """Microsoft's sign-in in a small pop-up inside the app (Link Xbox on a Verse profile).
        When Microsoft sends the player back to Verse, the pop-up closes and the main window
        loads that page, so the profile shows the new gamertag straight away. The pop-up gets
        no js_api, so Microsoft's pages can't call into the app."""
        p = urllib.parse.urlparse(url or "")
        if p.scheme != "https" or p.hostname not in self.SIGN_IN_HOSTS:
            log.warning("Sign-in pop-up refused for %s", p.hostname)
            return False
        import webview
        old = getattr(self, "signin_win", None)
        if old:
            try:
                old.destroy()
            except Exception:
                pass
        win = webview.create_window("Link Xbox", url, width=520, height=720, min_size=(420, 560),
                                    background_color="#0A0A0A")
        self.signin_win = win
        state = {"closed": False}

        def on_closed():
            state["closed"] = True
            if getattr(self, "signin_win", None) is win:
                self.signin_win = None

        win.events.closed += on_closed
        win.events.shown += lambda: dark_title_bar(win)
        threading.Thread(target=self._watch_sign_in, args=(win, state), daemon=True, name="signin").start()
        log.info("Sign-in pop-up opened")
        return True

    def _back_on_verse(self, url):
        """The page Microsoft finally sends the player to, as a Verse address, or None while
        they're still signing in. The /functions/ step is Verse working, not the end yet."""
        p = urllib.parse.urlparse(url or "")
        host = (p.hostname or "").lower()
        verse_host = (urllib.parse.urlparse(self.verse).hostname or "").lower()
        ours = self.on_verse(url) or host == verse_host or host.endswith(".base44.app")
        if not ours or p.path.startswith("/functions/"):
            return None
        return self.verse + (p.path or "/") + (("?" + p.query) if p.query else "")

    def _watch_sign_in(self, win, state):
        deadline = time.time() + 15 * 60
        while not state["closed"] and time.time() < deadline:
            time.sleep(0.4)
            try:
                url = win.get_current_url() or ""
            except Exception:
                continue
            back = self._back_on_verse(url)
            if back:
                log.info("Sign-in finished, refreshing Verse")
                try:
                    win.destroy()
                except Exception:
                    pass
                if self.window:
                    self.window.load_url(back)
                    self.show_window()
                return
        if not state["closed"]:
            try:
                win.destroy()
            except Exception:
                pass

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
        except Exception as e:
            log.error("Bad hotkey %r: %s", self.cfg["hotkey"], e)
            self.notice(f"The shortcut {pretty_hotkey(self.cfg['hotkey'])} can't be used, pick another")
            return False
        try:   # League item ideas on demand (Alt+Shift+I by default)
            if self.cfg.get("item_ideas_hotkey"):
                keyboard.add_hotkey(self.cfg["item_ideas_hotkey"], self.item_ideas.show_now)
        except Exception as e:
            log.warning("Item ideas shortcut %r can't be used: %s", self.cfg.get("item_ideas_hotkey"), e)
        return True

    def save_clip_async(self, *_):
        if self.rec:
            threading.Thread(target=self.rec.save_clip, daemon=True).start()

    def _watermark_loop(self):
        """Adds "Clipped by Verse Platform" to new clips, one at a time, in the background."""
        while True:
            clip_id = self.wm_queue.get()
            try:
                encoder = self.rec.encoder if self.rec else "libx264"
                # never while a game is being recorded: re-encoding a clip mid-game costs frames
                self.wait_for_game_end()
                encoder = self.rec.encoder if self.rec else "libx264"
                if self.library.add_watermark(clip_id, encoder):
                    self.bump()
            except Exception:
                log.exception("Watermark failed")

    def on_match(self, m):
        """League match details came in or changed: clips from now on go in that match's folder."""
        old = self.current_match
        self.current_match = m
        if self.rec and self.rec.label == m.get("game"):
            self.rec.subfolder = m["folder"]
        self.library.save_match(m)
        if not old or old.get("id") != m["id"] or old.get("result") != m.get("result"):
            self.bump()

    def on_match_summary(self, m):
        """End of a League game: keep the summary with the match so My clips can show it."""
        self.library.save_match(m)
        if self.current_match and self.current_match.get("id") == m["id"]:
            self.current_match = {**self.current_match, **m}
        self.bump()

    def trigger_save(self):
        """Voice command or controller combo: same as pressing the shortcut."""
        if self.rec and (self.rec.capturing or self.rec.segments()):
            self.rec.save_clip()

    def _auto_clean_loop(self):
        """Once a day: clips older than the chosen number of days that aren't starred or posted go."""
        time.sleep(90)
        while not self.quitting:
            days = int(self.cfg.get("auto_clean_days") or 0)
            if days:
                try:
                    old = self.library.old_clips(days)
                    if old:
                        n, _ = self.library.delete_many([c["id"] for c in old],
                                                        permanent=bool(self.cfg.get("auto_clean_permanent")))
                        log.info("Auto clean removed %d clips older than %d days", n, days)
                        if n:
                            self.bump()
                            self.notice(f"Cleaned up {n} old clip{'s' if n != 1 else ''}")
                except Exception:
                    log.exception("Auto clean failed")
            for _ in range(24 * 60):
                if self.quitting:
                    return
                time.sleep(60)

    def wait_for_game_end(self):
        """Heavy work (watermarks, squad copies, side by sides) waits until no game is being recorded."""
        while self.rec and self.rec.capturing and not self.quitting:
            time.sleep(5)

    def is_playing(self, game):
        return bool(self.rec and self.rec.capturing and self.rec.label == game)

    def save_highlight(self, label, start, end):
        self.save_q.put(("highlight", label, start, end))

    def on_death(self, game, t):
        """Death review: the lead up to every death, saved privately in the match's Deaths folder."""
        if self.cfg.get("death_review"):
            before = float(self.cfg.get("death_review_before", 10) or 10)
            self.save_q.put(("death", game, t - before, t + 2))

    def _save_loop(self):
        while True:
            job = self.save_q.get()
            try:
                kind, a, start, end = job
                wait = end + 2.5 - time.time()      # let the recorder finish the last chunk
                if wait > 0:
                    time.sleep(min(wait, 20))
                rec = self.rec
                if not rec or not (rec.capturing or rec.segments()):
                    continue
                if kind == "highlight":
                    path = rec.save_clip(tag=a, window=(start, end), wait=True)
                    if path:
                        clip = self.library.add(path)   # on_saved already added it, this just looks it up
                        self.squad.announce(clip, a, start, end)
                elif kind == "death":
                    n = 1 + sum(1 for c in self.library.list() if c.get("review") and c.get("match") ==
                                (self.current_match or {}).get("id"))
                    path = rec.save_clip(tag=f"Death {n}", window=(start, end), wait=True, quiet=True,
                                         folder_extra="Deaths")
                    if path:
                        self.add_saved_clip(path, f"Death {n}", extra={"review": True}, watermark=False)
                        log.info("Death review saved")
            except Exception:
                log.exception("Saving queued clip failed")

    def add_saved_clip(self, path, label, extra=None, match=None, watermark=True):
        """Adds a clip saved without the usual announcement (death reviews, squad POVs)."""
        game = self.rec.label if self.rec else ""
        if match is None:
            match = self.current_match["id"] if (self.current_match and self.rec and self.rec.subfolder) else None
        clip = self.library.add(path, game=game, highlight=label, match=match, extra=extra)
        self.bump()
        if clip and watermark and not clip.get("watermarked"):
            self.wm_queue.put(clip["id"])
        return clip

    def flash(self, title, sub=""):
        if self.cfg.get("show_save_overlay", True):
            self.overlay.show(title, accent="", sub=sub)
        else:
            self.notify(title, sub)
        self.notice(f"{title}: {sub}" if sub else title)

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
        match = self.current_match["id"] if (self.current_match and self.rec and self.rec.subfolder) else None
        # auto highlights end "highlight_after" seconds after the big moment; noting that lets the
        # watermark show the "Double kill" card right when it happens (the last 2s chunk can run a bit long)
        extra = {"moment_from_end": float(self.cfg.get("highlight_after", 5)) + 0.5} if tag else None
        clip = self.library.add(path, game=game, highlight=tag, match=match, extra=extra)
        self.library.bump_stat("clips_saved", tag)
        self.bump()
        if clip and self.cfg.get("clip_watermark", True):
            self.wm_queue.put(clip["id"])
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
                            self.follow_game_screen(rec)
                            if not rec.capturing:
                                rec.subfolder = ""          # new game: the next match folder comes from its details
                                self.current_match = None
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

    def follow_game_screen(self, rec):
        """Record the screen the game is on (multi screen setups), unless that's turned off."""
        if not self.cfg.get("follow_game_screen", True):
            rec.follow_screen(None)
            return
        hmon = self.watcher.game_screen()
        if hmon:
            rec.follow_screen(hmon)

    def popup_screen(self):
        """Where pop-ups go: the game's screen when we know it, else the screen picked in Settings."""
        rec = self.rec
        if rec and rec.screen:
            r = screen_rect(rec.screen)
            if r:
                return r
        return self.cfg.get("monitor", 0)

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
        if self.updater.use_pending():   # left over and already tried once at launch: just offer the button
            self.on_update_ready(self.updater.version, allow_auto=False)
        self.updater.start()
        self.highlights.start()
        self.item_ideas.start()
        try:
            token = (self.cfg.get("device_id") or "verse")[:20]
            port = GSIServer(int(self.cfg.get("gsi_port") or 3517), token, self.gsi_games).start()
            if port and IS_WINDOWS:
                self.gsi_setup = install_cfgs(port, token)
        except Exception:
            log.exception("CS2 / Dota 2 highlights setup failed")
        self.squad.start()
        self.pad.start()
        if self.cfg.get("voice_command"):
            self.voice.start()
        threading.Thread(target=self._auto_clean_loop, daemon=True, name="autoclean").start()

    # ------------------------------------------------------------ updates
    def on_update_ready(self, version, allow_auto=True):
        idle = allow_auto and not (self.rec and self.rec.capturing) and self.win_hidden
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
        log.info("Quitting")
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

    def open_sign_in(self, url):
        """Verse's Link Xbox button: Microsoft's sign-in opens in a pop-up inside the app,
        then the profile refreshes when it's done. Returns False if it can't, so Verse
        falls back to its normal way."""
        if not self._app.on_verse():
            return False
        return bool(self._app.open_sign_in(url))

    def dock_state(self):
        if not self._from_trusted():
            return None
        a = self._app
        return {"capturing": bool(a.rec and a.rec.capturing), "title": a.title,
                "clips": sum(1 for _ in a.library.list())}

    def whats_new(self):
        """Patch notes to show once after an update, or None."""
        if not (self._from_trusted() or self._from_library()):
            return None
        a = self._app
        seen = a.cfg.get("last_seen_version", "")
        if seen == APP_VERSION:
            return None
        if not seen and not a.library.list():
            a.cfg["last_seen_version"] = APP_VERSION   # brand new install: nothing to catch up on
            save_config(a.cfg)
            return None
        import whatsnew
        notes = whatsnew.unseen(seen or "1.0.0")
        if not notes:
            return None
        return {"version": APP_VERSION, "notes": [{"version": v, "html": h} for v, h in notes]}

    def whats_new_seen(self):
        if self._from_trusted() or self._from_library():
            self._app.cfg["last_seen_version"] = APP_VERSION
            save_config(self._app.cfg)

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
            **caption_info(clip, a.library.matches.get(clip.get("match") or "")),
        }

    def clip_published(self, clip_id, url=""):
        """Verse calls this after the post is live, so the library can show it as posted."""
        if not self._from_trusted():
            return None
        a = self._app
        a.library.mark_posted(str(clip_id), str(url or ""))
        a.library.bump_stat("posts")
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

    def check_updates(self):
        if not self._from_library():
            return None
        u = self._app.updater
        if not u.enabled:
            return {"message": "Updates aren't set up in this build"}
        if not u.version:
            try:
                u.check()
            except Exception as e:
                log.warning("Manual update check failed: %s", e)
                return {"message": "Couldn't reach the update server, try again soon"}
        if u.version:
            return {"message": f"Version {u.version} is ready. Click Update at the top to install it"}
        return {"message": f"You're on the latest version ({APP_VERSION})"}

    def list_matches(self):
        if not self._from_library():
            return None
        return self._app.library.list_matches()

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
        return self.delete_clips([clip_id])

    def delete_clips(self, clip_ids):
        if not self._from_library():
            return None
        deleted, failed = self._app.library.delete_many(list(clip_ids or []))
        self._app.bump()
        return {"deleted": deleted, "failed": failed}

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

    def publish_clip(self, clip_id, start, end, remove_voice=False):
        """Makes the trimmed copy, then opens Verse's Upload screen with the clip handed over."""
        if not self._from_library():
            return None
        a = self._app
        try:
            info = a.library.export(clip_id, start, end, a.rec.encoder if a.rec else "libx264",
                                    a.cfg.get("max_post_seconds", 60), watermark=a.cfg.get("clip_watermark", True),
                                    remove_voice=bool(remove_voice))
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
            "controller_combos": {k: v[0] for k, v in COMBOS.items()},
            "gsi_games": {g: bool(p) for g, p in a.gsi_setup.items()},
            "squad_error": a.squad.error,
        }

    def set_setting(self, key, value):
        if not self._from_library():
            return None
        a = self._app
        if key not in RESTART_KEYS and key not in LIVE_KEYS:
            return {"message": "Unknown setting"}
        if key == "squad_code":
            import re as _re
            value = _re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()[:12]
        if key == "squad_name":
            value = str(value or "").strip()[:24]
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
        if key == "voice_command":
            if value and not a.voice.start():
                a.cfg[key] = False
                save_config(a.cfg)
                return {"message": a.voice.error or "Voice command couldn't start"}
            if not value:
                a.voice.stop()
            return {"message": 'Say "clip that" to save a clip' if value else "Voice command off"}
        if key == "squad_code":
            return {"message": f"You're in squad {value}" if value else "Squad POV is off"}
        return {}

    def squad_new_code(self):
        if not self._from_library():
            return None
        a = self._app
        a.cfg["squad_code"] = make_code()
        save_config(a.cfg)
        return {"code": a.cfg["squad_code"]}

    def squad_status(self):
        if not self._from_library():
            return None
        sq = self._app.squad
        return {"code": sq.code, "name": sq.name(), "error": sq.error,
                "connected": bool(sq.last_ok and time.time() - sq.last_ok < 30)}

    # ---- clip tools
    def clip_tracks(self, clip_id):
        """How many sound tracks a clip has (2 = it was recorded with a mic, so the voice can be removed)."""
        if not self._from_library():
            return None
        from library import probe_audio_tracks
        c = self._app.library.get(clip_id)
        return probe_audio_tracks(self._app.ff, self._app.library.abs_path(c)) if c else 0

    def export_vertical(self, clip_id, start, end, mode="blur", remove_voice=False):
        if not self._from_library():
            return None
        a = self._app
        try:
            c = a.library.export_vertical(clip_id, start, end, mode if mode in ("blur", "crop") else "blur",
                                          a.rec.encoder if a.rec else "libx264",
                                          watermark=a.cfg.get("clip_watermark", True), remove_voice=bool(remove_voice))
        except ExportError as e:
            return {"error": str(e)}
        except Exception as e:
            log.exception("Vertical export failed")
            return {"error": f"Couldn't make the vertical clip ({e})"}
        a.bump()
        return {"ok": True, "id": c["id"], "title": c["title"]}

    def recap_preview(self):
        if not self._from_library():
            return None
        parts = self._app.library.recap_candidates()
        return {"count": len(parts), "seconds": round(sum(p["length"] for p in parts)),
                "titles": [p["clip"].get("title") for p in parts]}

    def make_recap(self):
        if not self._from_library():
            return None
        a = self._app
        try:
            c = a.library.make_recap(a.rec.encoder if a.rec else "libx264")
        except ExportError as e:
            return {"error": str(e)}
        except Exception as e:
            log.exception("Recap failed")
            return {"error": f"Couldn't make the recap ({e})"}
        if a.cfg.get("clip_watermark", True):
            a.wm_queue.put(c["id"])
        a.bump()
        return {"ok": True, "id": c["id"], "title": c["title"]}

    def set_star(self, clip_id, on):
        if self._from_library():
            self._app.library.set_star(clip_id, on)
            self._app.bump()
            return True

    def storage_info(self):
        if not self._from_library():
            return None
        a = self._app
        info = a.library.storage_info(int(a.cfg.get("auto_clean_days") or 0))
        info["folder"] = a.cfg["clips_folder"]
        return info

    def clean_now(self):
        if not self._from_library():
            return None
        a = self._app
        days = int(a.cfg.get("auto_clean_days") or 0)
        if not days:
            return {"message": "Pick how old clips should be first"}
        old = a.library.old_clips(days)
        n, failed = a.library.delete_many([c["id"] for c in old], permanent=bool(a.cfg.get("auto_clean_permanent")))
        a.bump()
        return {"message": f"Removed {n} old clip{'s' if n != 1 else ''}" + (f", {failed} were in use" if failed else "")}

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
    try:  # if the app ever crashes hard, write down where
        import faulthandler
        global _crash_file
        _crash_file = open(os.path.join(DATA_DIR, "crash.log"), "a", encoding="utf-8")
        faulthandler.enable(_crash_file)
    except Exception:
        pass
    threading.excepthook = lambda a: log.error("Thread %s crashed", a.thread.name if a.thread else "?",
                                               exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
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
    # an update downloaded last time but never installed (the app was closed suddenly): install it now
    upd = Updater(lambda v: None)
    found = upd.pending_on_disk() if upd.enabled else None
    if found:
        marker = os.path.join(DATA_DIR, "update_attempt.txt")
        try:
            with open(marker, encoding="utf-8") as f:
                tried = f.read().strip()
        except OSError:
            tried = ""
        if tried != found[0]:  # only try once per version, so a broken installer can't loop
            try:
                with open(marker, "w", encoding="utf-8") as f:
                    f.write(found[0])
            except OSError:
                pass
            upd.version, upd.path = found
            log.info("Installing update %s left over from last time", found[0])
            if upd.install(relaunch=True, background=background):
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
    app.window.events.shown += lambda: dark_title_bar(app.window)
    app.window.events.loaded += lambda: dark_title_bar(app.window)
    threading.Thread(target=app.boot, daemon=True).start()
    webview.start(gui="edgechromium" if IS_WINDOWS else None, private_mode=False,
                  storage_path=os.path.join(DATA_DIR, "webview"))
    app.quit()


def _hwnd(window):
    try:
        return int(window.native.Handle.ToInt64())
    except Exception:
        pass
    try:  # fallback: our own top level window with this title
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        u32.FindWindowW.restype = wintypes.HWND
        return u32.FindWindowW(None, APP_NAME) or 0
    except Exception:
        return 0


def dark_title_bar(window):
    """Black title bar with white text instead of Windows' default white one, so it matches
    the app and the logo stands out. Windows 11 takes the exact colour; Windows 10 gets dark mode."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = _hwnd(window)
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

        def put(attr, value):
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

        if put(20, 1) != 0:   # DWMWA_USE_IMMERSIVE_DARK_MODE (older Windows 10 builds used 19)
            put(19, 1)
        bgr = lambda r, g, b: r | (g << 8) | (b << 16)  # COLORREF
        put(35, bgr(0x0A, 0x0A, 0x0A))   # DWMWA_CAPTION_COLOR, same black as the app
        put(36, bgr(0xFF, 0xFF, 0xFF))   # DWMWA_TEXT_COLOR
        put(34, bgr(0x1A, 0x1A, 0x1A))   # DWMWA_BORDER_COLOR, a soft edge instead of a bright line
    except Exception:
        log.debug("dark title bar", exc_info=True)


if __name__ == "__main__":
    main()
