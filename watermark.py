"""
"Clipped by Verse Platform" watermark, burned into the first 3 seconds of a clip, and for auto
highlights a matching "Double kill" style card at the moment it happened.

It's a short animated title card, drawn frame by frame with Pillow and laid over the video:
  * the card glides in from the left and fades up (eased, no sudden jumps)
  * a cyan accent bar grows down its left edge
  * a soft light sweeps across the card once
  * it holds, then fades and drifts out
Being part of the video, it shows wherever the clip ends up: Verse, Discord, TikTok...
The frames are cached per video height in the temp folder, so they're only drawn once.
"""

import os
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from rewind_core import RES

SECONDS = 3.0
FPS = 30
VERSION = 2          # bump when the look changes, so old cached frames aren't reused

CYAN = (34, 211, 238)
WHITE = (247, 247, 250)
GREY = (168, 172, 184)
_cache = {}


# ---------------------------------------------------------------- drawing helpers
def _font(name, size):
    for path in (os.path.join(RES, "assets", "fonts", name),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts", name)):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    win = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")  # fallback: Segoe UI
    for n in ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"):
        if os.path.exists(os.path.join(win, n)):
            return ImageFont.truetype(os.path.join(win, n), size)
    return ImageFont.load_default()


def _logo(px):
    try:
        im = Image.open(os.path.join(RES, "assets", "logo.png")).convert("RGBA")
        im.thumbnail((px, px), Image.LANCZOS)
        return im
    except Exception:
        return None


def _spaced(draw, xy, text, font, fill, tracking):
    """Text with extra letter spacing (for the small CLIPPED BY label)."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x - tracking


def _ease_out(t):
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def _ease_in_out(t):
    t = min(1.0, max(0.0, t))
    return 3 * t * t - 2 * t * t * t


def _card(scale, label="CLIPPED BY", name=(("Verse ", None), ("Platform", "cyan"))):
    """The finished card (no animation), plus its parts we animate. Drawn at 2x for smooth edges.
    name: the big line, as (text, colour) pieces; colour None is white, "cyan" is the accent."""
    s = scale * 2
    pad_x, pad_y = int(20 * s), int(15 * s)
    logo_px = int(38 * s)
    gap = int(14 * s)
    f_label = _font("Inter-SemiBold.otf", int(10.5 * s))
    f_name = _font("InterDisplay-Bold.otf", int(21 * s))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tracking = 2.4 * s
    w_label = sum(probe.textlength(c, font=f_label) for c in label) + tracking * (len(label) - 1)
    w_name = sum(probe.textlength(t, font=f_name) for t, _ in name)
    text_w = max(w_label, w_name)
    w = int(pad_x + logo_px + gap + int(1.5 * s) + gap + text_w + pad_x * 1.15)
    h = int(logo_px + pad_y * 2)
    r = int(16 * s)

    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    # glassy dark body: a gentle top-to-bottom gradient
    body = Image.new("RGBA", (w, h))
    bd = ImageDraw.Draw(body)
    for y in range(h):
        k = y / max(1, h - 1)
        c = int(26 - 12 * k)
        bd.line([(0, y), (w, y)], fill=(c, c, c + 4, 236))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    card.paste(body, (0, 0), mask)
    d = ImageDraw.Draw(card)
    # hairline border, brighter along the top like light catching glass
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, outline=(255, 255, 255, 34), width=max(1, int(s)))
    d.line([(r, int(s)), (w - r, int(s))], fill=(255, 255, 255, 46), width=max(1, int(s)))

    lg = _logo(logo_px)
    lx = pad_x
    if lg:
        card.alpha_composite(lg, (lx, (h - lg.height) // 2))
    # thin divider between logo and text
    dx = lx + logo_px + gap
    d.line([(dx, int(h * 0.26)), (dx, int(h * 0.74))], fill=(255, 255, 255, 40), width=max(1, int(1.5 * s)))

    tx = dx + int(1.5 * s) + gap
    a_l, d_l = f_label.getmetrics()
    a_n, d_n = f_name.getmetrics()
    block = (a_l + d_l) + int(3 * s) + (a_n + d_n)
    ty = (h - block) // 2 + int(1 * s)
    _spaced(d, (tx, ty), label, f_label, GREY + (255,), tracking)
    ny = ty + a_l + d_l + int(3 * s)
    x = tx
    for text, colour in name:
        d.text((x, ny), text, font=f_name, fill=(CYAN if colour == "cyan" else WHITE) + (255,))
        x += probe.textlength(text, font=f_name)

    # soft shadow + faint cyan glow behind the card
    m = int(18 * s)
    full = Image.new("RGBA", (w + m * 2, h + m * 2), (0, 0, 0, 0))
    sh = Image.new("L", full.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((m, m + int(4 * s), m + w, m + h + int(4 * s)), radius=r, fill=150)
    sh = sh.filter(ImageFilter.GaussianBlur(int(9 * s)))
    full.paste((0, 0, 0, 255), (0, 0), sh)
    glow = Image.new("L", full.size, 0)
    ImageDraw.Draw(glow).rounded_rectangle((m, m + h - int(6 * s), m + w * 0.55, m + h + int(2 * s)), radius=r, fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(int(10 * s)))
    full.paste(CYAN + (255,), (0, 0), glow)
    full.alpha_composite(card, (m, m))
    return {"img": full, "m": m, "w": w, "h": h, "r": r, "s": s, "mask": mask}


def _frame(parts, t, length=None):
    """One frame of the animation at time t (seconds). Returns an RGBA image at 1x."""
    length = length or SECONDS
    full, m, w, h, r, s = parts["img"], parts["m"], parts["w"], parts["h"], parts["r"], parts["s"]
    slide = int(34 * s)
    out_w, out_h = full.width + slide, full.height
    frame = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))

    # in: 0 to 0.5s, out: last 0.45s
    t_in = _ease_out(t / 0.5)
    t_out = _ease_in_out((t - (length - 0.45)) / 0.45)
    alpha = t_in * (1 - t_out)
    if alpha <= 0.001:
        return frame.resize((max(1, out_w // 2), max(1, out_h // 2)), Image.LANCZOS)
    x = int(slide * t_in - slide * 0.6 * t_out)

    layer = full.copy()
    ld = ImageDraw.Draw(layer)
    # cyan accent bar on the left edge, growing from the middle (0.15s to 0.6s)
    grow = _ease_out((t - 0.15) / 0.45)
    if grow > 0:
        bar_h = (h - r * 1.2) * grow
        cy = m + h / 2
        ld.rounded_rectangle((m + int(5 * s), cy - bar_h / 2, m + int(8 * s), cy + bar_h / 2),
                             radius=int(2 * s), fill=CYAN + (255,))
    # one soft light sweep across the card (0.55s to 1.35s)
    sweep = (t - 0.55) / 0.8
    if 0 < sweep < 1:
        band = Image.new("L", layer.size, 0)
        bw = int(w * 0.22)
        cx = m - bw + int((w + bw * 2) * _ease_in_out(sweep))
        bdraw = ImageDraw.Draw(band)
        for i in range(bw):
            k = 1 - abs(i - bw / 2) / (bw / 2)
            bdraw.line([(cx + i + h * 0.35, m), (cx + i - h * 0.35, m + h)], fill=int(54 * k * k))
        clip = Image.new("L", layer.size, 0)
        clip.paste(parts["mask"], (m, m))
        band = ImageChops.multiply(band, clip)
        layer.paste((255, 255, 255, 255), (0, 0), ImageChops.multiply(band, layer.getchannel("A")))

    a = layer.getchannel("A").point(lambda v: int(v * alpha))
    layer.putalpha(a)
    frame.alpha_composite(layer, (max(0, x), 0))
    return frame.resize((max(1, out_w // 2), max(1, out_h // 2)), Image.LANCZOS)


# ---------------------------------------------------------------- used by library.py
HL_SECONDS = 2.6     # how long the highlight card ("Double kill") stays up


def _draw_set(folder, parts, length):
    frames = int(round(length * FPS))
    pattern = os.path.join(folder, "f_%03d.png")
    last = os.path.join(folder, f"f_{frames - 1:03d}.png")
    if not os.path.exists(last):
        os.makedirs(folder, exist_ok=True)
        tmp_names = []
        for i in range(frames):
            name = os.path.join(folder, f"f_{i:03d}.tmp.png")
            _frame(parts, i / FPS, length).save(name)
            tmp_names.append(name)
        for i, name in enumerate(tmp_names):  # rename at the end, so a half-drawn set is never used
            os.replace(name, os.path.join(folder, f"f_{i:03d}.png"))
    return pattern


def png_for(height):
    """Draws (once) the "Clipped by" frames for a video of this height. Returns the ffmpeg image
    sequence pattern for them."""
    height = int(height or 1080)
    key = ("tag", height)
    if key in _cache and os.path.exists(_cache[key].replace("%03d", f"{int(round(SECONDS * FPS)) - 1:03d}")):
        return _cache[key]
    folder = os.path.join(tempfile.gettempdir(), "VersePlatformWatermark", f"v{VERSION}_{height}")
    _cache[key] = _draw_set(folder, _card(max(0.7, height / 640)), SECONDS)
    return _cache[key]


def _highlight_name(label):
    """ "Triple kill + Ace" -> big line pieces, with the joining + in the accent colour."""
    bits = [b.strip() for b in str(label).split("+") if b.strip()]
    out = []
    for i, b in enumerate(bits):
        if i:
            out.append(("  +  ", "cyan"))
        out.append((b, None))
    return tuple(out) or ((str(label), None),)


def highlight_png_for(height, label, game=""):
    """Frames for the highlight card (e.g. "Double kill"), shown after the "Clipped by" one."""
    import hashlib
    height = int(height or 1080)
    small = f"{game} highlight".strip().upper() if game else "HIGHLIGHT"
    key = ("hl", height, label, small)
    if key in _cache:
        return _cache[key]
    h = hashlib.sha1(f"{label}|{small}".encode("utf-8")).hexdigest()[:10]
    folder = os.path.join(tempfile.gettempdir(), "VersePlatformWatermark", f"hl{VERSION}_{height}_{h}")
    _cache[key] = _draw_set(folder, _card(max(0.7, height / 640), small, _highlight_name(label)), HL_SECONDS)
    return _cache[key]


def highlight_time(clip_len, at):
    """When to show the highlight card: at the big moment, but never on top of the "Clipped by" tag
    and never cut off by the end of the clip. None if there's no room for it."""
    if at is None or clip_len < SECONDS + HL_SECONDS:
        return None
    t = max(SECONDS + 0.15, float(at))
    t = min(t, clip_len - HL_SECONDS)
    return t if t >= SECONDS else None


def inputs(pattern, offset=0.0):
    pre = ["-itsoffset", f"{offset:.3f}"] if offset else []
    return pre + ["-framerate", str(FPS), "-start_number", "0", "-i", pattern]


def filter_graph(pix_fmt="yuv420p", base="[0:v]", highlight=False):
    """Overlay the "Clipped by" animation (input 1) on the video (input 0, or another filter's output)
    for the first few seconds, then, with highlight=True, the highlight card (input 2, already
    shifted to its moment). Output label: [vo]."""
    pos = "x='W*0.022':y='H*0.035':eof_action=pass"
    if not highlight:
        return ("[1:v]format=rgba[wm];"
                f"{base}[wm]overlay={pos},format={pix_fmt}[vo]")
    return ("[1:v]format=rgba[wm];[2:v]format=rgba[hl];"
            f"{base}[wm]overlay={pos}[v1];"
            f"[v1][hl]overlay={pos},format={pix_fmt}[vo]")
