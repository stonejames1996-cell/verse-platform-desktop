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
HAZE = (160, 160, 170, 255)
SHOW_SECONDS = 3.2


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
    """Draws the pop-up. 'lead' is e.g. 'Last 60s saved by', 'accent' is coloured. Returns an RGBA image."""
    s = scale * 2  # draw at 2x then shrink, for smooth edges
    pad, gap, logo_px = int(14 * s), int(12 * s), int(30 * s)
    f_main, f_sub = _font(int(15 * s), bold=True), _font(int(12 * s))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w_lead = probe.textlength(lead + (" " if accent else ""), font=f_main)
    w_acc = probe.textlength(accent, font=f_main) if accent else 0
    w_sub = probe.textlength(sub, font=f_sub) if sub else 0
    text_w = max(w_lead + w_acc, w_sub)
    h = int((60 if sub else 50) * s)
    w = int(pad + logo_px + gap + text_w + pad * 1.4)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(12 * s)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=INK, outline=SEAM, width=max(1, int(s)))
    lg = _logo(logo_px)
    if lg:
        img.alpha_composite(lg, (pad, (h - lg.height) // 2))
    x = pad + logo_px + gap
    if sub:
        y1, y2 = int(11 * s), int(33 * s)
    else:
        asc, desc = f_main.getmetrics()
        y1 = (h - (asc + desc)) // 2
        y2 = 0
    d.text((x, y1), lead + (" " if accent else ""), font=f_main, fill=WHITE if ok else HAZE)
    if accent:
        d.text((x + w_lead, y1), accent, font=f_main, fill=SIGNAL)
    if sub:
        d.text((x, y2), sub, font=f_sub, fill=HAZE)
    return img.resize((max(1, w // 2), max(1, h // 2)), Image.LANCZOS)


def secs_text(secs):
    secs = int(round(secs))
    if secs < 120:
        return f"{secs}s"
    return f"{secs // 60} min" if secs % 60 == 0 else f"{secs // 60}m {secs % 60}s"


class Overlay:
    """Call show(...) from any thread. All Windows work happens on the overlay's own thread."""

    def __init__(self, get_monitor=lambda: 0):
        self.get_monitor = get_monitor
        self.q = queue.Queue()
        self.ok = IS_WINDOWS
        if self.ok:
            threading.Thread(target=self._run, daemon=True, name="overlay").start()

    def show(self, lead, accent="Verse Platform", sub="", ok=True):
        if self.ok:
            self.q.put((lead, accent, sub, ok))

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
                self._play(*item)
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
        wc.lpszClassName = "VersePlatformOverlay"
        u.RegisterClassExW(ctypes.byref(wc))
        WS_EX = 0x00080000 | 0x00000020 | 0x00000008 | 0x00000080 | 0x08000000  # layered transparent topmost toolwindow noactivate
        self.hwnd = u.CreateWindowExW(WS_EX, "VersePlatformOverlay", "Verse Platform", 0x80000000,  # WS_POPUP
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
        return ordered[idx] if idx < len(ordered) else (ordered[0] if ordered else (0, 0, 1920, 1080))

    def _scale(self):
        try:
            return max(1.0, self.u.GetDpiForSystem() / 96)
        except Exception:
            return 1.0

    def _play(self, lead, accent, sub, ok):
        ct, wt, u, g = self.ct, self.wt, self.u, self.g
        scale = self._scale()
        img = render(lead, accent, sub, scale, ok)
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
            left, top, _, _ = self._monitor_rect()
            margin = int(24 * scale)
            x0, y = left + margin, top + margin
            size, src = wt.SIZE(w, h), wt.POINT(0, 0)
            blend = self.BLENDFUNCTION(0, 0, 0, 1)

            def frame(alpha, dx):
                blend.SourceConstantAlpha = max(0, min(255, int(alpha)))
                dst = wt.POINT(x0 + int(dx), y)
                u.UpdateLayeredWindow(self.hwnd, screen, ct.byref(dst), ct.byref(size), mem, ct.byref(src), 0,
                                      ct.byref(blend), 2)  # ULW_ALPHA

            frame(0, -16 * scale)
            u.SetWindowPos(self.hwnd, wt.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)  # topmost, show, no activate
            ease = lambda t: 1 - (1 - t) ** 3
            for i in range(1, 13):  # ~200ms slide and fade in
                t = ease(i / 12)
                frame(255 * t, -16 * scale * (1 - t))
                time.sleep(1 / 60)
            end = time.time() + SHOW_SECONDS
            while time.time() < end and self.q.empty():
                self._pump()
                time.sleep(0.05)
            for i in range(1, 13):  # fade out
                frame(255 * (1 - i / 12), 0)
                time.sleep(1 / 60)
            u.ShowWindow(self.hwnd, 0)
        finally:
            g.SelectObject(mem, old)
            g.DeleteObject(bmp)
            g.DeleteDC(mem)
            u.ReleaseDC(None, screen)
