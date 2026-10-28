"""
"Last 60s saved by Verse Platform": a small pop-up drawn on top of the game when a clip saves.

It's a Windows layered window:
  * click-through and never takes focus, so the game keeps your mouse and keyboard
  * always on top of borderless / windowed games (exclusive fullscreen hides everything, like Game Bar)
  * hidden from screen capture (WDA_EXCLUDEFROMCAPTURE), so it never shows up in your own clips
The picture is drawn with Pillow (smooth corners, real transparency) and faded in and out.
"""

import logging
import os
import queue
import sys
import threading
import time

from PIL import Image, ImageDraw, ImageFont

from rewind_core import RES

log = logging.getLogger("verse.overlay")
IS_WINDOWS = sys.platform == "win32"

INK = (12, 12, 14, 232)
SEAM = (255, 255, 255, 30)
WHITE = (245, 245, 247, 255)
SIGNAL = (34, 211, 238, 255)
HAZE = (168, 172, 184, 255)
SHOW_SECONDS = 3.2
PLACE_KEYS = {"right": "strip", "left": "panel", "top": "popup"}   # overlay places -> saved position names


def _font(size, bold=False):
    names = (["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]) + \
            ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    folders = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"), "/usr/share/fonts/truetype/dejavu"]
    for n in names:
        for d in folders:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


_logo_cache = {}


def _logo(px):
    if px not in _logo_cache:
        try:
            im = Image.open(os.path.join(RES, "assets", "logo.png")).convert("RGBA")
            im.thumbnail((px, px), Image.LANCZOS)
            _logo_cache[px] = im
        except Exception:
            _logo_cache[px] = None
    return _logo_cache[px]


def render(lead, accent="Verse Platform", sub="", scale=1.0, ok=True):
    """Draws the pop-up in the same style as the "Clipped by Verse Platform" tag on clips: a glassy dark
    card with a soft shadow, a cyan accent bar (amber if something went wrong), the logo and a divider.
      * lead + accent, no sub ("Last 60s saved by" / "Verse Platform"): small spaced label over a big name
      * a title with a sub line (highlights, squad): bold title over a grey detail line
    Returns an RGBA image."""
    from watermark import _font, _spaced  # same fonts as the clip tag
    s = scale * 2  # draw at 2x then shrink, for smooth edges
    pad_x, pad_y, logo_px, gap = int(16 * s), int(12 * s), int(32 * s), int(12 * s)
    f_label = _font("Inter-SemiBold.otf", int(9.5 * s))
    f_big = _font("InterDisplay-Bold.otf", int(18 * s))
    f_title = _font("InterDisplay-Bold.otf", int(16 * s))
    f_sub = _font("Inter-SemiBold.otf", int(11.5 * s))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tracking = 2.0 * s
    mode = "tag" if (accent and not sub) else "title"
    if mode == "tag":
        label = lead.upper()
        w1 = sum(probe.textlength(c, font=f_label) for c in label) + tracking * max(0, len(label) - 1)
        first, _, rest = accent.partition(" ")
        w_first = probe.textlength(first + (" " if rest else ""), font=f_big)
        w2 = w_first + (probe.textlength(rest, font=f_big) if rest else 0)
        f1, f2 = f_label, f_big
    else:
        title = lead + (" " + accent if accent else "")
        w1 = probe.textlength(title, font=f_title)
        w2 = probe.textlength(sub, font=f_sub) if sub else 0
        f1, f2 = f_title, f_sub
    text_w = max(w1, w2)
    w = int(pad_x + logo_px + gap + int(1.5 * s) + gap + text_w + pad_x * 1.15)
    h = int(logo_px + pad_y * 2)
    r = int(14 * s)
    bar = SIGNAL[:3] if ok else (251, 191, 36)

    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    body = Image.new("RGBA", (w, h))
    bd = ImageDraw.Draw(body)
    for yy in range(h):
        c = int(26 - 12 * yy / max(1, h - 1))
        bd.line([(0, yy), (w, yy)], fill=(c, c, c + 4, 240))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    card.paste(body, (0, 0), mask)
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, outline=(255, 255, 255, 34), width=max(1, int(s)))
    d.line([(r, int(s)), (w - r, int(s))], fill=(255, 255, 255, 46), width=max(1, int(s)))
    bar_h = h - r * 1.2
    d.rounded_rectangle((int(5 * s), (h - bar_h) / 2, int(8 * s), (h + bar_h) / 2), radius=int(2 * s), fill=bar + (255,))
    lg = _logo(logo_px)
    if lg:
        card.alpha_composite(lg, (pad_x, (h - lg.height) // 2))
    dx = pad_x + logo_px + gap
    d.line([(dx, int(h * 0.26)), (dx, int(h * 0.74))], fill=(255, 255, 255, 40), width=max(1, int(1.5 * s)))
    tx = dx + int(1.5 * s) + gap
    a1, d1 = f1.getmetrics()
    a2, d2 = f2.getmetrics()
    two = mode == "tag" or bool(sub)
    if two:
        block = a1 + d1 + int(3 * s) + a2 + d2
        y1 = (h - block) // 2 + int(1 * s)
        y2 = y1 + a1 + d1 + int(3 * s)
    else:
        y1 = (h - (a1 + d1)) // 2
    if mode == "tag":
        _spaced(d, (tx, y1), label, f_label, HAZE, tracking)
        d.text((tx, y2), first + (" " if rest else ""), font=f_big, fill=WHITE)
        if rest:
            d.text((tx + w_first, y2), rest, font=f_big, fill=SIGNAL)
    else:
        d.text((tx, y1), lead + (" " if accent else ""), font=f_title, fill=WHITE)
        if accent:
            d.text((tx + probe.textlength(lead + " ", font=f_title), y1), accent, font=f_title, fill=SIGNAL)
        if sub:
            d.text((tx, y2), sub, font=f_sub, fill=HAZE)

    m = int(12 * s)  # room for the soft shadow
    full = Image.new("RGBA", (w + m * 2, h + m * 2), (0, 0, 0, 0))
    sh = Image.new("L", full.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((m, m + int(3 * s), m + w, m + h + int(3 * s)), radius=r, fill=130)
    from PIL import ImageFilter
    full.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(int(7 * s))))
    full.alpha_composite(card, (m, m))
    return full.resize((max(1, full.width // 2), max(1, full.height // 2)), Image.LANCZOS)


def secs_text(secs):
    secs = int(round(secs))
    if secs < 120:
        return f"{secs}s"
    return f"{secs // 60} min" if secs % 60 == 0 else f"{secs // 60}m {secs % 60}s"


class Overlay:
    """Call show(...) from any thread. All Windows work happens on the overlay's own thread."""

    def __init__(self, get_monitor=lambda: 0, name="VersePlatformOverlay", get_positions=lambda: {}):
        """get_monitor: a screen number (0 = main) or a (left, top, right, bottom) rectangle.
        name: its own window class, so several overlays (pop-ups, League timers) can be up at once.
        get_positions: where the player dragged each kind of overlay to (see MoveMode), as screen fractions."""
        self.get_monitor = get_monitor
        self.get_positions = get_positions
        self.name = name
        self.q = queue.Queue()
        self.ok = IS_WINDOWS
        if self.ok:
            threading.Thread(target=self._run, daemon=True, name="overlay").start()

    def show(self, lead, accent="Verse Platform", sub="", ok=True):
        if self.ok:
            self.q.put(("msg", lead, accent, sub, ok))

    def show_image(self, img, seconds=SHOW_SECONDS, until=None, place="top", in_clips=False):
        """Shows a ready drawn RGBA picture. until: optional check, the pop-up goes as soon as it
        returns False (e.g. the item ideas leave when you respawn). place: "top" or "left".
        in_clips: let it show up in recordings (the item ideas do, it's good for Verse to be seen)."""
        if self.ok:
            self.q.put(("img", img, seconds, until, place, in_clips))

    def show_static(self, img, place="right"):
        """Shows (or replaces) a picture that stays up with no animation until hide_static()."""
        if self.ok:
            self.q.put(("static", img, place))

    def hide_static(self):
        if self.ok:
            self.q.put(("hide",))

    def scale(self):
        try:
            return self._scale()
        except Exception:
            return 1.0

    # ---------------------------------------------------------------- Windows only below
    def _run(self):
        try:
            self._setup()
        except Exception:
            log.exception("Overlay unavailable")
            self.ok = False
            return
        while True:
            try:
                item = self.q.get(timeout=0.25)
            except queue.Empty:
                self._pump()
                continue
            while not self.q.empty():  # only the newest message matters
                item = self.q.get_nowait()
            try:
                if item[0] == "img":
                    self._present(*item[1:])
                elif item[0] == "static":
                    self._present(item[1], 0, None, item[2], static=True)
                elif item[0] == "hide":
                    self.u.ShowWindow(self.hwnd, 0)
                else:
                    self._play(*item[1:])
            except Exception:
                log.exception("Overlay failed to draw")

    def _setup(self):
        import ctypes
        from ctypes import wintypes as wt
        self.ct, self.wt = ctypes, wt
        u, g = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("gdi32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u, self.g = u, g
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                        ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]

        u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.DefWindowProcW.restype = LRESULT
        u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        u.CreateWindowExW.restype = wt.HWND
        u.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        u.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
        u.GetDC.argtypes = [wt.HWND]
        u.GetDC.restype = wt.HDC
        u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        u.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
        u.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
        g.CreateCompatibleDC.argtypes = [wt.HDC]
        g.CreateCompatibleDC.restype = wt.HDC
        g.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
        g.CreateDIBSection.restype = wt.HBITMAP
        g.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
        g.SelectObject.restype = wt.HGDIOBJ
        g.DeleteObject.argtypes = [wt.HGDIOBJ]
        g.DeleteDC.argtypes = [wt.HDC]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                        ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]
        self.BLENDFUNCTION = BLENDFUNCTION
        u.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE), wt.HDC,
                                          ctypes.POINTER(wt.POINT), wt.COLORREF, ctypes.POINTER(BLENDFUNCTION), wt.DWORD]

        self._proc = WNDPROC(lambda h, m, w, l: u.DefWindowProcW(h, m, w, l))  # keep a reference
        k.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        k.GetModuleHandleW.restype = wt.HMODULE  # 64-bit handle, don't let ctypes cut it to an int
        u.SetWindowDisplayAffinity.argtypes = [wt.HWND, wt.DWORD]
        u.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.c_void_p, ctypes.c_void_p, wt.LPARAM]
        hinst = k.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = self.name
        u.RegisterClassExW(ctypes.byref(wc))
        WS_EX = 0x00080000 | 0x00000020 | 0x00000008 | 0x00000080 | 0x08000000  # layered transparent topmost toolwindow noactivate
        self.hwnd = u.CreateWindowExW(WS_EX, self.name, "Verse Platform", 0x80000000,  # WS_POPUP
                                      0, 0, 1, 1, None, None, hinst, None)
        if not self.hwnd:
            raise OSError(ctypes.get_last_error(), "CreateWindowEx failed")
        try:  # keep the pop-up out of recordings (Windows 10 2004 and newer)
            u.SetWindowDisplayAffinity(self.hwnd, 0x11)
        except Exception:
            pass

    def _pump(self):
        msg = self.wt.MSG()
        while self.u.PeekMessageW(self.ct.byref(msg), None, 0, 0, 1):  # PM_REMOVE
            self.u.TranslateMessage(self.ct.byref(msg))
            self.u.DispatchMessageW(self.ct.byref(msg))

    def _monitor_rect(self):
        ct, wt, u = self.ct, self.wt, self.u
        rects = []
        MONITORENUMPROC = ct.WINFUNCTYPE(ct.c_int, wt.HMONITOR, wt.HDC, ct.POINTER(wt.RECT), wt.LPARAM)

        def cb(hmon, hdc, prc, lp):
            r = prc.contents
            rects.append((r.left, r.top, r.right, r.bottom))
            return 1
        proc = MONITORENUMPROC(cb)
        u.EnumDisplayMonitors(None, None, ct.cast(proc, ct.c_void_p), 0)
        primary = [r for r in rects if r[0] == 0 and r[1] == 0]
        ordered = primary + [r for r in rects if r not in primary]
        idx = self.get_monitor() or 0
        if isinstance(idx, (tuple, list)):   # the game's screen, as a rectangle
            return tuple(idx)
        return ordered[idx] if idx < len(ordered) else (ordered[0] if ordered else (0, 0, 1920, 1080))

    def _scale(self):
        try:
            return max(1.0, self.u.GetDpiForSystem() / 96)
        except Exception:
            return 1.0

    def _play(self, lead, accent, sub, ok):
        self._present(render(lead, accent, sub, self._scale(), ok), SHOW_SECONDS, None, "top")

    def _present(self, img, seconds, until, place, in_clips=False, static=False):
        ct, wt, u, g = self.ct, self.wt, self.u, self.g
        try:   # save pop-ups stay out of recordings, the item ideas can be in them
            u.SetWindowDisplayAffinity(self.hwnd, 0 if in_clips else 0x11)
        except Exception:
            pass
        scale = self._scale()
        w, h = img.size
        # premultiplied BGRA, which is what UpdateLayeredWindow wants
        r_, g_, b_, a_ = img.split()
        from PIL import ImageChops
        r_, g_, b_ = (ImageChops.multiply(c, a_) for c in (r_, g_, b_))
        data = Image.merge("RGBA", (b_, g_, r_, a_)).tobytes()

        class BITMAPINFOHEADER(ct.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", ct.c_long), ("biHeight", ct.c_long), ("biPlanes", wt.WORD),
                        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                        ("biXPelsPerMeter", ct.c_long), ("biYPelsPerMeter", ct.c_long), ("biClrUsed", wt.DWORD),
                        ("biClrImportant", wt.DWORD)]
        bmi = BITMAPINFOHEADER(ct.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        screen = u.GetDC(None)
        mem = g.CreateCompatibleDC(screen)
        bits = ct.c_void_p()
        bmp = g.CreateDIBSection(screen, ct.byref(bmi), 0, ct.byref(bits), None, 0)
        old = g.SelectObject(mem, bmp)
        try:
            ct.memmove(bits, data, len(data))
            left, top, right, bottom = self._monitor_rect()
            margin = int(24 * scale)
            x0, y = left + margin, top + margin
            if place == "left":   # middle of the left edge, a little above centre (clear of chat)
                y = max(top + margin, top + (bottom - top - h) // 2 - (bottom - top) // 12)
            elif place == "right":   # right edge, a third of the way down (clear of the scoreboard and minimap)
                x0, y = right - margin - w, top + int((bottom - top) * 0.30)
            try:   # moved by the player (Alt+Shift+M): top left corner as a share of the screen
                pos = (self.get_positions() or {}).get(PLACE_KEYS.get(place, place))
            except Exception:
                pos = None
            if pos:
                x0 = left + int(float(pos[0]) * (right - left))
                y = top + int(float(pos[1]) * (bottom - top))
                x0 = max(left, min(x0, right - w))
                y = max(top, min(y, bottom - h))
            size, src = wt.SIZE(w, h), wt.POINT(0, 0)
            blend = self.BLENDFUNCTION(0, 0, 0, 1)

            def frame(alpha, dx):
                blend.SourceConstantAlpha = max(0, min(255, int(alpha)))
                dst = wt.POINT(x0 + int(dx), y)
                u.UpdateLayeredWindow(self.hwnd, screen, ct.byref(dst), ct.byref(size), mem, ct.byref(src), 0,
                                      ct.byref(blend), 2)  # ULW_ALPHA

            if static:   # no animation, stays up until replaced or hidden
                frame(255, 0)
                u.SetWindowPos(self.hwnd, wt.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
                return
            frame(0, -16 * scale)
            u.SetWindowPos(self.hwnd, wt.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)  # topmost, show, no activate
            ease = lambda t: 1 - (1 - t) ** 3
            for i in range(1, 13):  # ~200ms slide and fade in
                t = ease(i / 12)
                frame(255 * t, -16 * scale * (1 - t))
                time.sleep(1 / 60)
            end, next_check = time.time() + seconds, time.time() + 1
            while time.time() < end and self.q.empty():
                self._pump()
                time.sleep(0.05)
                if until and time.time() >= next_check:
                    next_check = time.time() + 1
                    try:
                        if not until():
                            break
                    except Exception:
                        break
            for i in range(1, 13):  # fade out
                frame(255 * (1 - i / 12), 0)
                time.sleep(1 / 60)
            u.ShowWindow(self.hwnd, 0)
        finally:
            g.SelectObject(mem, old)
            g.DeleteObject(bmp)
            g.DeleteDC(mem)
            u.ReleaseDC(None, screen)


# ---------------------------------------------------------------- moving the overlays
_MOVE_CLASS = None   # (window procedure, user32, class) kept alive for the whole run, see MoveMode._run


class MoveMode:
    """Alt+Shift+M: a labelled box for each overlay that the player can drag anywhere. Press it again and
    the spots are saved as shares of the screen (so they survive resolution and screen changes)."""

    ITEMS = (("strip", "Stats box", 170, 270), ("panel", "Stats and item ideas", 330, 520), ("popup", "Save and summary pop-ups", 360, 74))

    def __init__(self, get_rect, current, on_done, key_name="Alt+Shift+M"):
        """get_rect() -> (left, top, right, bottom) of the game's screen; current: saved positions;
        on_done(positions) is called with the new spots when move mode ends."""
        self.get_rect, self.current, self.on_done = get_rect, dict(current or {}), on_done
        self.key_name = key_name
        self.stop_flag = threading.Event()
        self.ok = IS_WINDOWS
        if self.ok:
            threading.Thread(target=self._run, daemon=True, name="overlay-move").start()

    def stop(self):
        self.stop_flag.set()

    def _card(self, label, w, h, scale):
        from watermark import _font
        s = scale * 2
        W, H = int(w * s), int(h * s)
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((0, 0, W - 1, H - 1), radius=int(12 * s), fill=(10, 14, 19, 200))
        dash, gap, c = int(10 * s), int(6 * s), SIGNAL
        for x in range(int(12 * s), W - int(12 * s), dash + gap):   # dashed cyan border
            d.line([(x, int(s)), (min(x + dash, W), int(s))], fill=c, width=max(2, int(1.5 * s)))
            d.line([(x, H - 1 - int(s)), (min(x + dash, W), H - 1 - int(s))], fill=c, width=max(2, int(1.5 * s)))
        for y in range(int(12 * s), H - int(12 * s), dash + gap):
            d.line([(int(s), y), (int(s), min(y + dash, H))], fill=c, width=max(2, int(1.5 * s)))
            d.line([(W - 1 - int(s), y), (W - 1 - int(s), min(y + dash, H))], fill=c, width=max(2, int(1.5 * s)))
        f1, f2 = _font("InterDisplay-Bold.otf", int(13 * s)), _font("Inter-SemiBold.otf", int(10 * s))
        t1, t2 = label, f"Drag me. {self.key_name} to finish"
        cy = H // 2 - (int(13 * s) if h > 60 else int(11 * s))
        d.text(((W - d.textlength(t1, font=f1)) // 2, cy), t1, font=f1, fill=WHITE)
        d.text(((W - d.textlength(t2, font=f2)) // 2, cy + int(19 * s)), t2, font=f2, fill=HAZE)
        return im.resize((W // 2, H // 2), Image.LANCZOS)

    def _run(self):
        import ctypes
        from ctypes import wintypes as wt
        from PIL import ImageChops
        try:
            u, g = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
            k = ctypes.WinDLL("kernel32")
            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

            class WNDCLASSEXW(ctypes.Structure):
                _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                            ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                            ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                            ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]

            class BLENDFUNCTION(ctypes.Structure):
                _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                            ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                            ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                            ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                            ("biClrImportant", wt.DWORD)]
            u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
            u.DefWindowProcW.restype = LRESULT
            u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
            u.CreateWindowExW.restype = wt.HWND
            u.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
            u.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE), wt.HDC,
                                              ctypes.POINTER(wt.POINT), wt.COLORREF, ctypes.POINTER(BLENDFUNCTION), wt.DWORD]
            u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
            u.DestroyWindow.argtypes = [wt.HWND]
            u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
            u.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
            u.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
            u.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
            u.GetDC.argtypes = [wt.HWND]
            u.GetDC.restype = wt.HDC
            u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
            g.CreateCompatibleDC.argtypes = [wt.HDC]
            g.CreateCompatibleDC.restype = wt.HDC
            g.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
            g.CreateDIBSection.restype = wt.HBITMAP
            g.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
            g.SelectObject.restype = wt.HGDIOBJ
            g.DeleteObject.argtypes = [wt.HGDIOBJ]
            g.DeleteDC.argtypes = [wt.HDC]
            k.GetModuleHandleW.argtypes = [wt.LPCWSTR]
            k.GetModuleHandleW.restype = wt.HMODULE

            hinst = k.GetModuleHandleW(None)
            # Windows keeps a window class for the whole run, pointing at this window procedure. It must live as
            # long as the app does (a module global), or opening move mode a second time crashes the app.
            global _MOVE_CLASS
            if _MOVE_CLASS is None:
                def proc(h, m, w, l):
                    if m == 0x0084:        # WM_NCHITTEST: the whole box is a handle Windows drags for us
                        return 2           # HTCAPTION
                    if m == 0x0021:        # WM_MOUSEACTIVATE: don't steal focus from the game
                        return 3           # MA_NOACTIVATE
                    return u.DefWindowProcW(h, m, w, l)
                wndproc = WNDPROC(proc)
                wc = WNDCLASSEXW()
                wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
                wc.lpfnWndProc = wndproc
                wc.hInstance = hinst
                u.LoadCursorW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
                u.LoadCursorW.restype = wt.HANDLE
                wc.hCursor = u.LoadCursorW(None, ctypes.c_void_p(32646))   # IDC_SIZEALL, the move cursor
                wc.lpszClassName = "VersePlatformMove"
                if not u.RegisterClassExW(ctypes.byref(wc)):
                    raise OSError("Couldn't set up the move boxes")
                _MOVE_CLASS = (wndproc, u, wc)     # keep every piece alive for the rest of the run
            try:
                scale = max(1.0, u.GetDpiForSystem() / 96)
            except Exception:
                scale = 1.0
            left, top, right, bottom = self.get_rect()
            sw, sh = right - left, bottom - top
            margin = int(24 * scale)
            defaults = {"strip": (right - margin - 170 * scale, top + sh * 0.30),
                        "panel": (left + margin, top + sh * 0.25), "popup": (left + margin, top + margin)}
            screen = u.GetDC(None)
            wins = {}
            for key, label, w, h in self.ITEMS:
                img = self._card(label, w, h, scale)
                iw, ih = img.size
                pos = self.current.get(key)
                x, y = (left + float(pos[0]) * sw, top + float(pos[1]) * sh) if pos else defaults[key]
                x, y = int(max(left, min(x, right - iw))), int(max(top, min(y, bottom - ih)))
                hwnd = u.CreateWindowExW(0x00080000 | 0x00000008 | 0x00000080 | 0x08000000,   # layered topmost toolwindow noactivate
                                         "VersePlatformMove", label, 0x80000000, x, y, iw, ih, None, None, hinst, None)
                if not hwnd:
                    log.warning("Couldn't open the move box for %s", label)
                    continue
                r_, g_, b_, a_ = img.split()
                r_, g_, b_ = (ImageChops.multiply(c, a_) for c in (r_, g_, b_))
                data = Image.merge("RGBA", (b_, g_, r_, a_)).tobytes()
                bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), iw, -ih, 1, 32, 0, 0, 0, 0, 0, 0)
                mem = g.CreateCompatibleDC(screen)
                bits = ctypes.c_void_p()
                bmp = g.CreateDIBSection(screen, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
                old = g.SelectObject(mem, bmp)
                ctypes.memmove(bits, data, len(data))
                blend = BLENDFUNCTION(0, 0, 255, 1)
                u.UpdateLayeredWindow(hwnd, screen, ctypes.byref(wt.POINT(x, y)), ctypes.byref(wt.SIZE(iw, ih)), mem,
                                      ctypes.byref(wt.POINT(0, 0)), 0, ctypes.byref(blend), 2)
                g.SelectObject(mem, old)
                g.DeleteObject(bmp)
                g.DeleteDC(mem)
                u.SetWindowPos(hwnd, wt.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
                wins[key] = hwnd
            u.ReleaseDC(None, screen)
            msg = wt.MSG()
            while not self.stop_flag.is_set():
                while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    u.TranslateMessage(ctypes.byref(msg))
                    u.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.01)
            out = {}
            for key, hwnd in wins.items():
                rc = wt.RECT()
                if u.GetWindowRect(hwnd, ctypes.byref(rc)):
                    out[key] = [round((rc.left - left) / max(1, sw), 4), round((rc.top - top) / max(1, sh), 4)]
                u.DestroyWindow(hwnd)
            self.on_done(out)
        except Exception:
            log.exception("Move mode failed")
            try:
                self.on_done(None)
            except Exception:
                pass
