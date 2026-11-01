"""THE FINALS auto highlights.

The Finals has no live game data for apps (League and CS2 do), so this reads the game's own pop-ups
instead: every elimination, team wipe and cashout shows a banner just under the crosshair, e.g.

    ELIMINATED SOMEONE  $100        TEAM WIPE  BONUS        TEAM STOLE A CASHOUT  BONUS $1,000

The recorder hands us a small grey copy of that part of the screen 4 times a second (see TAP_W in
rewind_core) and Windows' own built-in text recognition reads it. Nothing touches the game: it's the
same picture that's already being recorded.
"""
import asyncio
import difflib
import logging
import re
import threading
import time

from gsi import GameTracker

log = logging.getLogger("Verse Platform")

GAME = "The Finals"
CHAIN = 6.0          # seconds allowed between eliminations for them to count as a double, triple...
MULTI = {2: ("double", "Double kill", 4), 3: ("triple", "Triple kill", 6),
         4: ("quadra", "Quad kill", 9), 5: ("penta", "Penta kill", 10)}


def is_finals(label):
    return (label or "").strip().lower() == GAME.lower()


# ------------------------------------------------------------------------- reading the banner text

def _tokens(line):
    """'ELIMINATED Bob_42  $100' -> ['ELIMINATED', 'BOB_42', '$100']. Common OCR mix-ups fixed."""
    return re.findall(r"[A-Z0-9_$,.+|#-]+", line.upper())


def _like(tok, word, cut=0.8):
    if tok == word:
        return True
    if abs(len(tok) - len(word)) > 3:
        return False
    return difflib.SequenceMatcher(None, tok, word).ratio() >= cut


def _has(tokens, word, cut=0.8):
    return any(_like(t, word, cut) for t in tokens)


def _eliminated_name(tokens):
    """The name after ELIMINATED ('?' if the name couldn't be read: it's red and often too faint),
    or None if this line isn't a kill banner. The reward line under it reads 'ELIMINATION | +250'
    (sometimes read as 'ELIMINA TION'), and that one must not count as another kill."""
    glued = "".join(tokens)
    if re.search(r"ELIM[I1L]NA\W*T[I1L][O0]N", glued) or "TION" in tokens:
        return None
    for i, t in enumerate(tokens):
        if t.endswith(("ION", "I0N", "LON")) or not _like(t, "ELIMINATED", 0.78):
            continue
        name = []
        for nt in tokens[i + 1:]:
            if nt.startswith(("$", "+", "|")) or re.fullmatch(r"[\d,.$+]+", nt):
                break
            name.append(nt)
        return " ".join(name) or "?"
    return None


def parse(lines):
    """Banner lines -> list of (kind, detail). kind: 'elim' (detail = the name), 'wipe', 'steal', 'cashout'."""
    found = []
    for line in lines:
        tk = _tokens(line)
        if not tk:
            continue
        name = _eliminated_name(tk)
        if name:
            found.append(("elim", name))
            continue
        text = " ".join(tk)
        cash = "CASH" in text or _has(tk, "CASHOUT", 0.75)
        if _has(tk, "WIPE") and _has(tk, "TEAM"):
            found.append(("wipe", ""))
        elif cash and _has(tk, "STOLE"):
            found.append(("steal", ""))
        elif cash and (_has(tk, "BONUS") or "CASHED" in text or _has(tk, "COMPLETED", 0.75)):
            found.append(("cashout", ""))
    return found


class WindowsOcr:
    """Windows' built-in text recognition (the same one the Snipping Tool uses). No download needed."""

    def __init__(self):
        self.engine = None
        self.ok = None
        self.loop = None

    def _load(self):
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.media.ocr import OcrEngine
            eng = OcrEngine.try_create_from_language(Language("en-US"))
            if eng is None:
                eng = OcrEngine.try_create_from_user_profile_languages()
            self.engine = eng
            self.loop = asyncio.new_event_loop()
            self.ok = eng is not None
            if not self.ok:
                log.warning("The Finals highlights: Windows text recognition isn't available on this PC")
        except Exception:
            log.warning("The Finals highlights: couldn't start Windows text recognition", exc_info=True)
            self.ok = False
        return self.ok

    def read(self, img):
        """img: a PIL 'L' (grey) picture. Returns the lines of text found."""
        if self.ok is None:
            self._load()
        if not self.ok:
            return []
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter
        rgba = img.convert("RGBA")
        r, g, b, a = rgba.split()
        from PIL import Image
        bgra = Image.merge("RGBA", (b, g, r, a))     # Windows wants blue, green, red, alpha
        w, h = bgra.size
        dw = DataWriter()
        dw.write_bytes(bgra.tobytes())
        bmp = SoftwareBitmap.create_copy_from_buffer(dw.detach_buffer(), BitmapPixelFormat.BGRA8, w, h)
        result = self.loop.run_until_complete(self.engine.recognize_async(bmp))
        return [ln.text for ln in result.lines]


def prepare(img):
    """The banner text is white (names red, bonuses yellow) over the game. Two versions for the reader:
    the picture with stronger contrast, and a cut-out of just the bright parts as dark text on white."""
    from PIL import ImageOps
    big = img.resize((img.width * 3 // 2, img.height * 3 // 2))
    plain = ImageOps.autocontrast(big, cutoff=1)
    bright = big.point(lambda v: 0 if v >= 170 else 255)
    return [plain, bright]


def has_bright_text(img):
    """Cheap check before reading: is there enough bright, banner-like stuff in the middle band?"""
    band = img.crop((img.width // 8, img.height // 4, img.width * 7 // 8, img.height * 3 // 4))
    hist = band.histogram()
    bright = sum(hist[200:])
    return bright > band.width * band.height * 0.004


# ------------------------------------------------------------------------- turning banners into highlights

class FinalsHighlights(GameTracker):
    GAME = GAME
    CHAIN = CHAIN

    def __init__(self, *a, ocr=None, **k):
        super().__init__(*a, **k)
        self.ocr = ocr or WindowsOcr()
        self.reset()
        self._frame = None
        self._wake = threading.Event()
        threading.Thread(target=self._read_loop, daemon=True, name="finals-ocr").start()

    def reset(self):
        self.names = {}         # name on a kill banner -> when it was last seen
        self.kills = []         # times of the eliminations in the current chain
        self.last = {}          # 'wipe' / 'steal' / 'cashout' -> when it was last counted
        self.lines_logged = 0

    def handle(self, data, now):   # not used: no game data feed
        pass

    # called from the recorder's tap thread: just keep the newest frame, never block it
    def feed_frame(self, buf, w, h, t):
        if not self.get_cfg().get("auto_highlights", True):
            return
        self._frame = (buf, w, h, t)
        self._wake.set()

    def _read_loop(self):
        from PIL import Image
        while True:
            self._wake.wait()
            self._wake.clear()
            frame, self._frame = self._frame, None
            if not frame:
                continue
            buf, w, h, t = frame
            try:
                img = Image.frombytes("L", (w, h), buf)
                if not has_bright_text(img):
                    self.see([], t)
                    continue
                lines = []
                for version in prepare(img):
                    got = self.ocr.read(version)
                    lines += got
                    if parse(got):
                        break
                self.see(lines, t)
            except Exception:
                log.debug("The Finals banner read failed", exc_info=True)

    def see(self, lines, t):
        """What the banner said at time t. Works out new eliminations and other moments."""
        events = parse(lines)
        if lines and not events and self.lines_logged < 40 and any("CASH" in ln.upper() for ln in lines):
            self.lines_logged += 1   # helps us learn banners we don't know yet (e.g. other cashout wording)
            log.info("The Finals banner not understood: %s", " / ".join(lines)[:120])
        for kind, detail in events:
            if kind == "elim":
                self._elim(detail, t)
            else:
                gap = {"wipe": 8, "steal": 15, "cashout": 15}[kind]
                if t - self.last.get(kind, 0) > gap:
                    self.last[kind] = t
                    self._moment(kind, t)
        for n in [n for n, seen in self.names.items() if t - seen > 4]:
            del self.names[n]

    def _elim(self, name, t):
        key = re.sub(r"[^A-Z0-9]", "", name.upper())
        same = None
        for k, seen in self.names.items():
            # the same banner over several frames, even if the reader gets a letter or two wrong
            if t - seen <= 1.6 and (k == key or difflib.SequenceMatcher(None, k, key).ratio() >= 0.6):
                same = k
                break
        if same is not None:
            self.names[same] = t
            return
        self.names[key] = t
        if self.kills and t - self.kills[-1] <= CHAIN:
            self.kills.append(t)
        else:
            self.kills = [t]
        n = len(self.kills)
        log.info("The Finals: elimination (%d in a row)", n)
        self.hit("every_kill", "Kill", 1, t)
        if n >= 2:
            key2, text, rank = MULTI[min(n, 5)]
            self.hit(key2, text, rank, t, start=self.kills[0])

    def _moment(self, kind, t):
        start = self.kills[0] if self.kills and t - self.kills[-1] <= CHAIN else None
        if kind == "wipe":
            self.hit("team_wipe", "Team wipe", 8, t, start=start)
        elif kind == "steal":
            self.hit("cashout_steal", "Cashout steal", 9, t, start=start)
        elif kind == "cashout":
            self.hit("cashout", "Cashout", 7, t, start=start)
