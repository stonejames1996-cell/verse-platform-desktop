"""Pictures for The Finals overlays (drawn with Pillow, shown by overlay.py):
  * render_title: a pop-up on each elimination ("Double kill", "Team wipe"), like League's (shows in clips)
  * render_box: "your game so far" (eliminations, team wipes, cashouts, steals, best multi, cash)
  * render_summary: the session summary when the game closes, vs your usual
Only the player's own numbers, read from their own on-screen pop-ups. Same look as the League boxes."""
import os

from PIL import Image, ImageDraw, ImageFilter

INK = (16, 16, 20, 214)
WHITE = (245, 245, 247, 255)
HAZE = (168, 172, 184, 255)
CYAN = (13, 162, 231, 255)   # Verse blue (name kept)
PINK = (255, 122, 196, 255)
GOLD = (250, 204, 21, 255)
RED = (211, 31, 60, 255)      # The Finals' own red
UP, DOWN = (52, 211, 153, 255), (251, 191, 36, 255)

HEADLINES = {2: "DOUBLE", 3: "TRIPLE", 4: "QUAD"}


def _res(*parts):
    from rewind_core import RES
    return os.path.join(RES, *parts)


def _img(path, px):
    try:
        im = Image.open(path).convert("RGBA")
        im.thumbnail((px, px), Image.LANCZOS)
        return im
    except Exception:
        return None


def verse_logo(px):
    return _img(_res("assets", "logo.png"), px)


def finals_logo(px):
    return _img(_res("ui", "games", "the-finals.png"), px)


def _fonts(s):
    from watermark import _font
    return {
        "label": _font("Inter-SemiBold.otf", int(7.5 * s)),
        "row": _font("Inter-SemiBold.otf", int(10.5 * s)),
        "val": _font("InterDisplay-Bold.otf", int(11 * s)),
    }


def _lh(f):
    return sum(f.getmetrics())


def _finish(card, s, r):
    """Soft shadow, then down to half size (drawn at 2x so edges stay smooth)."""
    m = int(8 * s)
    full = Image.new("RGBA", (card.width + m * 2, card.height + m * 2), (0, 0, 0, 0))
    sh = Image.new("L", full.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((m, m + int(2 * s), m + card.width, m + card.height + int(2 * s)), radius=r, fill=110)
    full.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(int(5 * s))))
    full.alpha_composite(card, (m, m))
    return full.resize((max(1, full.width // 2), max(1, full.height // 2)), Image.LANCZOS)


# ---------------------------------------------------------------- the game's own icons
# THE FINALS Wiki's copies of the game's loading screen icons. The app downloads them the first time it
# needs them and keeps a cut-out copy (background removed) next to its settings, like League's champion
# pictures. They're Embark's artwork, so they're not shipped in this (public) repo. If they can't be
# fetched, the drawn icons below are used instead.
WIKI = "https://www.thefinals.wiki/w/images/"
GAME_ICONS = {
    "elims": "6/61/Icon_LoadingScreen_Eliminated.png",
    "wipes": "7/73/Icon_LoadingScreen_GhoulRush_Survivors_Cropped.png",
    "cashouts": "6/68/Icon_LoadingScreen_Deposit_Station.png",
    "steals": "e/e9/Icon_LoadingScreen_Cashbox.png",
    "cash": "3/3b/Icon_LoadingScreen_Coins.png",
}
_game_icons = {}


def cut_out(im):
    """The icons sit on a pale grey backdrop: make the pale, colourless parts see-through and trim."""
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            mx, mn = max(r, g, b), min(r, g, b)
            sat = (mx - mn) / mx if mx else 0
            if sat < 0.22 and mx > 120:
                px[x, y] = (r, g, b, 0)
            elif sat < 0.32 and mx > 110:
                px[x, y] = (r, g, b, int(a * (sat - 0.22) / 0.10))
    box = im.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
    if box:
        x0, y0, x1, y1 = box
        side = max(x1 - x0, y1 - y0) + 8
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(im.crop((int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2))), (0, 0))
        im = sq
    return im.resize((96, 96), Image.LANCZOS)


def game_icon(kind):
    """The cut-out game icon (96px), downloading it once if needed. None if it isn't available."""
    if kind in _game_icons:
        return _game_icons[kind]
    path_part = GAME_ICONS.get(kind)
    im = None
    if path_part:
        from rewind_core import DATA_DIR
        folder = os.path.join(DATA_DIR, "finals_icons")
        local = os.path.join(folder, kind + ".png")
        try:
            if os.path.exists(local):
                im = Image.open(local).convert("RGBA")
            else:
                import io
                import urllib.request
                req = urllib.request.Request(WIKI + path_part, headers={"User-Agent": "VersePlatform"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    im = cut_out(Image.open(io.BytesIO(r.read())))
                os.makedirs(folder, exist_ok=True)
                im.save(local)
        except Exception:
            im = None
    _game_icons[kind] = im
    return im


def preload_icons():
    """Fetch the game icons in the background when The Finals starts, so the first pop-up isn't slowed."""
    import threading

    def go():
        for k in GAME_ICONS:
            game_icon(k)
    threading.Thread(target=go, daemon=True, name="finals-icons").start()


# ---------------------------------------------------------------- little icons, drawn as a fallback
def icon(kind, px, col=CYAN):
    real = game_icon(kind)
    if real is not None:
        return real.resize((px, px), Image.LANCZOS)
    return drawn_icon(kind, px, col)


def drawn_icon(kind, px, col=CYAN):
    im = Image.new("RGBA", (px * 4, px * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    P = px * 4
    w = max(2, P // 11)
    c = P // 2
    if kind == "elims":          # crosshair
        d.ellipse((P * .2, P * .2, P * .8, P * .8), outline=col, width=w)
        for a, b in (((c, P * .04), (c, P * .3)), ((c, P * .7), (c, P * .96)),
                     ((P * .04, c), (P * .3, c)), ((P * .7, c), (P * .96, c))):
            d.line((a, b), fill=col, width=w)
        d.ellipse((c - w, c - w, c + w, c + w), fill=col)
    elif kind == "wipes":        # three heads, crossed out
        for x in (.22, .5, .78):
            d.ellipse((P * (x - .13), P * .3, P * (x + .13), P * .56), fill=col)
            d.rounded_rectangle((P * (x - .17), P * .6, P * (x + .17), P * .86), radius=P // 10, fill=col)
        d.line((P * .08, P * .92, P * .92, P * .08), fill=PINK, width=int(w * 1.2))
    elif kind == "cashouts":     # vault door
        d.rounded_rectangle((P * .1, P * .1, P * .9, P * .9), radius=P // 8, outline=col, width=w)
        d.ellipse((P * .3, P * .3, P * .7, P * .7), outline=col, width=w)
        for a in ((c, P * .3, c, P * .7), (P * .3, c, P * .7, c)):
            d.line(a, fill=col, width=max(1, w // 2))
    elif kind == "steals":       # two arrows swapping
        d.line((P * .12, P * .35, P * .82, P * .35), fill=col, width=w)
        d.polygon([(P * .9, P * .35), (P * .7, P * .2), (P * .7, P * .5)], fill=col)
        d.line((P * .88, P * .68, P * .18, P * .68), fill=col, width=w)
        d.polygon([(P * .1, P * .68), (P * .3, P * .53), (P * .3, P * .83)], fill=col)
    elif kind == "best":         # lightning bolt
        d.polygon([(P * .58, P * .04), (P * .2, P * .56), (P * .46, P * .56), (P * .38, P * .96),
                   (P * .8, P * .4), (P * .54, P * .4)], fill=col)
    elif kind == "cash":         # coin with $
        from watermark import _font
        d.ellipse((P * .06, P * .06, P * .94, P * .94), outline=col, width=w)
        f = _font("InterDisplay-Bold.otf", int(P * .56))
        tw = d.textlength("$", font=f)
        d.text((c - tw / 2, P * .17), "$", font=f, fill=col)
    return im.resize((px, px), Image.LANCZOS)


def money(n):
    return f"${int(n):,}"


# ---------------------------------------------------------------- the elimination pop-up
TITLES = {1: "Elimination", 2: "Double kill", 3: "Triple kill", 4: "Quad kill"}


def title_for(n, wipe=False):
    return "Team wipe" if wipe else ("Multi-kill" if n >= 5 else TITLES.get(n, "Elimination"))


def render_title(n, wipe=False, cash=0, scale=1.0, screen_h=1080):
    """The same card League's highlights get in clips ("THE FINALS HIGHLIGHT" over "Double kill"), drawn the
    size it is in a clip of this screen's height, so it sits exactly where the "Clipped by" card was."""
    import watermark
    parts = watermark._card(max(0.7, screen_h / 640), "THE FINALS HIGHLIGHT",
                            watermark._highlight_name(title_for(n, wipe)))
    return watermark._frame(parts, watermark.HL_SECONDS / 2, watermark.HL_SECONDS)


# ---------------------------------------------------------------- your game so far
ROWS = (("elims", "Eliminations"), ("wipes", "Team wipes"), ("cashouts", "Cashouts"),
        ("steals", "Steals"), ("best", "Best multi kill"), ("cash", "Cash earned"))


def render_box(stats, scale=1.0):
    s = scale * 2
    f = _fonts(s)
    pad, gap = int(10 * s), int(6 * s)
    ic = int(17 * s)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    vals = {k: (money(stats.get(k, 0)) if k == "cash" else str(stats.get(k, 0))) for k, _ in ROWS}
    lab_w = max(probe.textlength(lab, font=f["row"]) for _, lab in ROWS)
    val_w = max(probe.textlength(v, font=f["val"]) for v in vals.values())
    w = int(pad * 2 + ic + 6 * s + lab_w + 14 * s + val_w)
    w = max(w, int(170 * s))
    row_h = max(_lh(f["row"]), ic)
    h = pad + int(16 * s) + len(ROWS) * (row_h + gap) - gap + pad
    r = int(10 * s)
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=INK, outline=(255, 255, 255, 30), width=max(1, int(s)))
    from watermark import _spaced
    lg = finals_logo(int(11 * s))
    x = pad
    if lg:
        card.alpha_composite(lg, (x, pad - int(1 * s)))
        x += lg.width + int(5 * s)
    _spaced(d, (x, pad), "YOUR GAME SO FAR", f["label"], HAZE, 1.4 * s)
    vl = verse_logo(int(11 * s))
    if vl:
        card.alpha_composite(vl, (w - pad - vl.width, pad - int(1 * s)))
    y = pad + int(16 * s)
    for k, lab in ROWS:
        cy = y + row_h // 2
        card.alpha_composite(icon(k, ic, GOLD if k == "cash" else CYAN), (pad, cy - ic // 2))
        d.text((pad + ic + int(6 * s), y + (row_h - _lh(f["row"])) // 2), lab, font=f["row"], fill=WHITE)
        v = vals[k]
        vw = probe.textlength(v, font=f["val"])
        d.text((w - pad - vw, y + (row_h - _lh(f["val"])) // 2), v, font=f["val"], fill=GOLD if k == "cash" else WHITE)
        y += row_h + gap
    return _finish(card, s, r)


# ---------------------------------------------------------------- the session summary
def compare(now, avg):
    """'up' / 'down' / '' against your usual (4% either way counts as the same)."""
    if avg is None or now is None:
        return ""
    if now > avg * 1.04:
        return "up"
    if now < avg * 0.96:
        return "down"
    return ""


def render_summary(summary, avg=None, scale=1.0):
    """End of a session: big tiles for each number, with your usual underneath when there is one."""
    from watermark import _font, _spaced
    avg = avg or {}
    s = scale * 2
    pad = int(14 * s)
    tile_w, tile_h, tg = int(92 * s), int(62 * s), int(8 * s)
    cols = 3
    w = pad * 2 + cols * tile_w + (cols - 1) * tg
    h = pad + int(34 * s) + 2 * tile_h + tg + pad
    r = int(12 * s)
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=INK, outline=(255, 255, 255, 34), width=max(1, int(s)))
    f_t = _font("InterDisplay-Bold.otf", int(13 * s))
    f_l = _font("Inter-SemiBold.otf", int(7.5 * s))
    f_v = _font("InterDisplay-Bold.otf", int(20 * s))
    f_a = _font("Inter-SemiBold.otf", int(7.5 * s))
    lg = finals_logo(int(20 * s))
    x = pad
    if lg:
        card.alpha_composite(lg, (x, pad))
        x += lg.width + int(8 * s)
    d.text((x, pad - int(1 * s)), "Session summary", font=f_t, fill=WHITE)
    mins = int(summary.get("minutes") or 0)
    sub = f"THE FINALS  ·  {mins // 60}h {mins % 60}m" if mins >= 60 else f"THE FINALS  ·  {mins} min"
    _spaced(d, (x, pad + int(16 * s)), sub, f_l, HAZE, 1.2 * s)
    vl = verse_logo(int(20 * s))
    if vl:
        card.alpha_composite(vl, (w - pad - vl.width, pad))
    y0 = pad + int(34 * s)
    for i, (k, lab) in enumerate(ROWS):
        tx = pad + (i % cols) * (tile_w + tg)
        ty = y0 + (i // cols) * (tile_h + tg)
        d.rounded_rectangle((tx, ty, tx + tile_w, ty + tile_h), radius=int(8 * s), fill=(255, 255, 255, 12))
        ic = int(15 * s)
        card.alpha_composite(icon(k, ic, GOLD if k == "cash" else CYAN), (tx + int(7 * s), ty + int(6 * s)))
        d.text((tx + int(7 * s) + ic + int(4 * s), ty + int(10 * s)), lab, font=f_l, fill=HAZE)
        now = summary.get(k, 0)
        v = money(now) if k == "cash" else str(now)
        d.text((tx + int(8 * s), ty + int(22 * s)), v, font=f_v, fill=GOLD if k == "cash" else WHITE)
        if k in avg:
            st = compare(now, avg[k])
            a = money(avg[k]) if k == "cash" else f"{avg[k]:.1f}".rstrip("0").rstrip(".")
            txt = f"usual {a}" + (" ▲" if st == "up" else " ▼" if st == "down" else "")
            d.text((tx + int(8 * s), ty + int(47 * s)), txt, font=f_a,
                   fill=UP if st == "up" else DOWN if st == "down" else HAZE)
    return _finish(card, s, r)
