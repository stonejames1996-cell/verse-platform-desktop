"""
Squad POV: when you and your mates share a squad code, a highlight on one PC is clipped from
everyone's screen at the same moment, and the clips come back to you as one side by side video.

How it works:
  1. You get a highlight -> your app tells the squad ("Pantriel, Triple kill, from 12:31 to 12:44").
  2. Your mates' apps (if they're in the same game) save that exact stretch from their own screen,
     straight from their recording buffer, into their own library ("Pantriel's Triple kill").
  3. If they share their POV (on by default), a small copy goes to Verse and your app builds
     "Squad POV: Triple kill" with both screens side by side.

The messages go through a small function on the Verse website (squadRelay). Nothing is sent
unless a squad code is set. League games line up to the frame using the game clock both PCs
share; other games use each PC's clock (Windows keeps those within a second or so).
"""

import base64
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import urllib.request

from library import LOW_PRIORITY, NO_WINDOW, probe_duration

log = logging.getLogger("verse.squad")

POLL_EVERY = 4          # seconds, only while a game is being recorded
MAX_AGE = 90            # ignore signals older than this, the moment is out of the buffer by then
POV_HEIGHT = 540        # the copy sent to the squad is small: 960x540
POV_BITRATE = "1500k"


def relay_secret():
    """Key that lets the app use Verse's squadRelay. The GitHub build bakes it into the installer
    from a repo secret (it's never in the public code). VERSE_SQUAD_SECRET overrides it for testing."""
    if os.environ.get("VERSE_SQUAD_SECRET"):
        return os.environ["VERSE_SQUAD_SECRET"]
    from rewind_core import RES
    try:
        with open(os.path.join(RES, "squad_secret.txt"), encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return ""


def make_code():
    import secrets
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I mix ups
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _video_args(enc):
    if enc == "libx264":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]
    return ["-c:v", enc, "-b:v", "10M", "-maxrate", "12M", "-bufsize", "12M"]


def _label_png(text, path):
    """A small name tag like the save pop-up, e.g. "Pantriel"."""
    from PIL import Image, ImageDraw, ImageFont
    font = None
    for f in (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(f):
            font = ImageFont.truetype(f, 26)
            break
    font = font or ImageFont.load_default()
    w = int(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(text, font=font)) + 32
    img = Image.new("RGBA", (w, 44), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, 43), radius=10, fill=(10, 10, 10, 200))
    d.rectangle((0, 8, 3, 35), fill=(34, 211, 238, 255))
    d.text((18, 6), text, font=font, fill=(255, 255, 255, 255))
    img.save(path)
    return path


def side_by_side(ff, mine, theirs, offset, out, my_name, their_name, encoder="libx264"):
    """Both screens next to each other on a 1920x1080 canvas, lined up in time.
    offset: how many seconds after my clip's start theirs starts (can be negative). Sound is mine."""
    dur = probe_duration(ff, mine) or 30
    tmp = tempfile.mkdtemp(prefix="verse_squad_")
    a = _label_png(my_name, os.path.join(tmp, "a.png"))
    b = _label_png(their_name, os.path.join(tmp, "b.png"))
    their_in = ["-i", theirs]
    pad = ""
    if offset < 0:
        their_in = ["-ss", f"{-offset:.3f}", "-i", theirs]
    elif offset > 0.05:
        pad = f",tpad=start_duration={offset:.3f}:start_mode=add:color=black"
    graph = ("[0:v]scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2,setsar=1[l];"
             f"[1:v]scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=60{pad}[r];"
             "[l]fps=60[l2];[l2][r]hstack=inputs=2:shortest=0[s];"
             "[s]pad=1920:1080:0:270:color=0x0A0A0A[p];"
             "[p][2:v]overlay=24:290[p2];[p2][3:v]overlay=984:290,format=yuv420p[v]")

    def cmd(enc):
        return ([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", mine] + their_in +
                ["-loop", "1", "-i", a, "-loop", "1", "-i", b, "-filter_complex", graph,
                 "-map", "[v]", "-map", "0:a:0?", "-t", f"{dur:.3f}"] + _video_args(enc) +
                ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out])
    err = ""
    try:
        for enc in ([encoder, "libx264"] if encoder != "libx264" else ["libx264"]):
            r = subprocess.run(cmd(enc), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900,
                               creationflags=NO_WINDOW | LOW_PRIORITY)
            if r.returncode == 0 and os.path.exists(out):
                return True, ""
            err = r.stderr.decode(errors="replace").strip()[-300:]
            log.warning("Squad POV encode with %s failed: %s", enc, err)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return False, err


def small_copy(ff, src, out):
    """The 960x540 copy of your POV that gets sent to your squad mate."""
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-map", "0:v:0", "-map", "0:a:0?",
                        "-vf", f"scale=-2:{POV_HEIGHT}", "-c:v", "libx264", "-preset", "veryfast",
                        "-b:v", POV_BITRATE, "-maxrate", POV_BITRATE, "-bufsize", "3000k",
                        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600, creationflags=NO_WINDOW | LOW_PRIORITY)
    return r.returncode == 0 and os.path.exists(out)


class Squad:
    """Talks to the squad. 'app' is the desktop App (recorder, library, highlights, settings)."""

    def __init__(self, app):
        self.app = app
        self.since = None          # server time of the last poll, so nothing is seen twice
        self.mine = {}             # signal id -> {"clip_id", "start", "label", "game", "at"}
        self.done = set()          # signal / pov ids already handled
        self.error = ""
        self.last_ok = 0.0

    # ------------------------------------------------------------- basics
    @property
    def cfg(self):
        return self.app.cfg

    @property
    def code(self):
        return str(self.cfg.get("squad_code") or "").strip().upper()

    def name(self):
        n = str(self.cfg.get("squad_name") or "").strip()
        if n:
            return n[:24]
        me = getattr(self.app.highlights, "me_name", "") or ""
        return (me.split("#")[0] or os.environ.get("USERNAME") or "Squad mate")[:24]

    def endpoint(self):
        from urllib.parse import quote
        return self.app.verse + "/functions/squadRelay?secret=" + quote(relay_secret())

    def _post(self, payload, timeout=15):
        payload = dict(payload, squad=self.code, device=self.cfg.get("device_id", ""), name=self.name())
        req = urllib.request.Request(self.endpoint(), data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "VersePlatform"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="squad").start()

    def _active(self):
        rec = self.app.rec
        return bool(self.code and rec and rec.capturing and rec.label)

    # ------------------------------------------------------------- times
    def _league(self, game):
        return game == "League of Legends" and getattr(self.app.highlights, "offset", None) is not None

    def to_shared(self, game, wall):
        """This PC's time -> the time both PCs agree on (League game clock, otherwise wall clock)."""
        return round(self.app.highlights.to_game(wall), 3) if self._league(game) else round(wall, 3)

    def from_shared(self, game, t, clock):
        if clock == "game":
            return self.app.highlights.to_wall(t) if self._league(game) else None
        return t

    # ------------------------------------------------------------- my highlight -> tell the squad
    def announce(self, clip, label, start, end):
        """Called after one of my auto highlights saved."""
        if not self.code or not clip:
            return
        game = clip.get("game") or ""
        actual = getattr(self.app.rec, "last_start", 0.0) or start
        clock = "game" if self._league(game) else "wall"

        def go():
            try:
                ign = getattr(self.app.highlights, "me_name", "") if game == "League of Legends" else ""
                r = self._post({"action": "signal", "game": game, "label": label, "clock": clock, "ign": ign,
                                "start": self.to_shared(game, start), "end": self.to_shared(game, end)})
                sid = str(r.get("id") or "")
                if sid:
                    self.mine[sid] = {"clip_id": clip["id"], "start": self.to_shared(game, actual), "label": label,
                                      "game": game, "at": time.time()}
                    log.info("Told the squad about %s", label)
            except Exception as e:
                self._fail(e)
        threading.Thread(target=go, daemon=True).start()

    # ------------------------------------------------------------- polling
    def _loop(self):
        while True:
            time.sleep(POLL_EVERY)
            if not self._active() and not self._waiting_for_povs():
                continue
            try:
                r = self._post({"action": "poll", "since": self.since})
                self.since = r.get("now") or self.since
                self.last_ok = time.time()
                self.error = ""
                for s in r.get("signals") or []:
                    self._on_signal(s)
                for p in r.get("povs") or []:
                    self._on_pov(p)
            except Exception as e:
                self._fail(e)

    def _waiting_for_povs(self):
        now = time.time()
        self.mine = {k: v for k, v in self.mine.items() if now - v["at"] < 600}
        return bool(self.code and self.mine)

    def _fail(self, e):
        msg = str(e)
        if "404" in msg:
            msg = "Squad POV isn't switched on at Verse yet"
        if msg != self.error:
            log.warning("Squad: %s", msg)
        self.error = msg

    # ------------------------------------------------------------- a squad mate's highlight -> save my POV
    def _on_signal(self, s):
        sid = str(s.get("id") or "")
        if not sid or sid in self.done or s.get("device") == self.cfg.get("device_id"):
            return
        self.done.add(sid)
        rec, game = self.app.rec, s.get("game") or ""
        if not rec or not rec.capturing or rec.label != game:
            return       # not playing that game right now
        if game == "League of Legends":
            # only clip it if they're in this match with you (League lists every player's name)
            players = getattr(self.app.highlights, "players", set()) or set()
            ign = str(s.get("ign") or "").strip().lower()
            if players and ign and ign not in players and ign.split("#")[0] not in players:
                return
        start = self.from_shared(game, float(s.get("start") or 0), s.get("clock"))
        end = self.from_shared(game, float(s.get("end") or 0), s.get("clock"))
        if start is None or end is None or time.time() - end > MAX_AGE:
            return
        who = str(s.get("name") or "Squad mate")[:24]
        label = f"{who}'s {s.get('label') or 'highlight'}"
        threading.Thread(target=self._save_pov, args=(sid, who, label, game, start, end), daemon=True).start()

    def _save_pov(self, sid, who, label, game, start, end):
        a = self.app
        wait = end + 2.5 - time.time()
        if wait > 0:
            time.sleep(min(wait, 30))
        path = a.rec.save_clip(tag=label, window=(start, end), wait=True, quiet=True)
        if not path:
            return
        actual = getattr(a.rec, "last_start", 0.0) or start
        clip = a.add_saved_clip(path, label, extra={"squad": {"of": who, "signal": sid}})
        log.info("Saved your POV of %s", label)
        a.flash(f"Squad POV saved", sub=label)
        if not clip or not self.cfg.get("squad_share", True):
            return
        tmp = os.path.join(tempfile.gettempdir(), f"verse_pov_{sid}.mp4")
        try:
            if small_copy(a.ff, path, tmp):
                with open(tmp, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                self._post({"action": "pov", "signal_id": sid, "start": self.to_shared(game, actual),
                            "video_b64": data, "file_name": "pov.mp4"}, timeout=120)
                log.info("Sent your POV of %s to %s", label, who)
        except Exception as e:
            self._fail(e)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # ------------------------------------------------------------- their POV came back -> side by side
    def _on_pov(self, p):
        pid = str(p.get("id") or "")
        sid = str(p.get("signal_id") or "")
        if not pid or pid in self.done or sid not in self.mine or not p.get("file_url"):
            return
        self.done.add(pid)
        threading.Thread(target=self._combine, args=(p, self.mine[sid]), daemon=True).start()

    def _combine(self, p, mine):
        a = self.app
        clip = a.library.get(mine["clip_id"])
        if not clip:
            return
        tmp = os.path.join(tempfile.gettempdir(), f"verse_squad_{p['id']}.mp4")
        try:
            req = urllib.request.Request(p["file_url"], headers={"User-Agent": "VersePlatform"})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                f.write(r.read())
            src = a.library.abs_path(clip)
            out = os.path.join(os.path.dirname(src), f"Squad POV {os.path.splitext(os.path.basename(src))[0]}.mp4")
            offset = float(p.get("start") or 0) - float(mine["start"] or 0)
            who = str(p.get("name") or "Squad mate")[:24]
            ok, err = side_by_side(a.ff, src, tmp, offset, out, self.name(), who,
                                   a.rec.encoder if a.rec else "libx264")
            if not ok:
                log.warning("Squad POV couldn't be made: %s", err)
                return
            title = f"Squad POV: {mine['label']}"
            c = a.add_saved_clip(out, title, extra={"squad_combo": True, "squad": {"with": who}}, match=clip.get("match"))
            a.flash("Squad POV ready", sub=f"{mine['label']} with {who}")
            log.info("Made %s with %s", title, who)
        except Exception:
            log.exception("Squad POV failed")
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
