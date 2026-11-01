"""Pictures for The Finals overlays (drawn with Pillow, shown by overlay.py):
  * render_combo: the Verse combo counter that pops up on each elimination (shows in clips)
  * render_box: "your game so far" (eliminations, team wipes, cashouts, steals, best multi, cash)
  * render_summary: the session summary when the game closes, vs your usual
Only the player's own numbers, read from their own on-screen pop-ups. Same look as the League boxes."""
import os

from PIL import Image, ImageDraw, ImageFilter

INK = (16, 16, 20, 214)
WHITE = (245, 245, 247, 255)
HAZE = (168, 172, 184, 255)
CYAN = (34, 211, 238, 255)
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


# ---------------------------------------------------------------- little icons, drawn not typed
def icon(kind, px, col=CYAN):
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


# ---------------------------------------------------------------- the combo counter
def render_combo(n, wipe=False, cash=0, scale=1.0):
    """The Verse combo counter: logo, VERSE COMBO, the number of eliminations in this chain, and a
    headline (DOUBLE / TRIPLE / QUAD / MULTI-KILL / TEAM WIPE!). Cash won in the chain underneath."""
    from watermark import _font
    s = scale * 2
    accent = PINK if wipe else CYAN
    w, h = int(232 * s), int(96 * s)
    r = int(12 * s)
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=INK, outline=accent[:3] + (150,), width=max(1, int(s)))
    d.rounded_rectangle((int(9 * s), int(12 * s), int(13 * s), h - int(12 * s)), radius=int(2 * s), fill=accent)
    x = int(22 * s)
    logo = verse_logo(int(16 * s))
    if logo:
        card.alpha_composite(logo, (x, int(9 * s)))
    f_brand = _font("InterDisplay-Bold.otf", int(9.5 * s))
    f_small = _font("Inter-SemiBold.otf", int(8.5 * s))
    d.text((x + int(20 * s), int(11 * s)), "VERSE", font=f_brand, fill=WHITE)
    bw = d.textlength("VERSE", font=f_brand)
    d.text((x + int(20 * s) + bw + int(6 * s), int(12 * s)), "COMBO", font=f_small, fill=HAZE)
    head = "TEAM WIPE!" if wipe else ("MULTI-KILL" if n >= 5 else HEADLINES.get(n, ""))
    if head:
        f_head = _font("InterDisplay-Bold.otf", int(13 * s))
        hw = d.textlength(head, font=f_head)
        d.text((w - int(12 * s) - hw, int(8 * s)), head, font=f_head, fill=accent)
    f_big = _font("InterDisplay-Bold.otf", int(46 * s))
    num = str(n)
    d.text((x, int(28 * s)), num, font=f_big, fill=WHITE)
    nw = d.textlength(num, font=f_big)
    f_word = _font("InterDisplay-Bold.otf", int(15 * s))
    word = "ELIMINATION" if n == 1 else "ELIMINATIONS"
    d.text((x + nw + int(9 * s), int(45 * s)), word, font=f_word, fill=accent)
    if cash:
        d.text((x + nw + int(9 * s), int(66 * s)), f"+{money(cash)} this fight", font=f_small, fill=GOLD)
    return _finish(card, s, r)


# ---------------------------------------------------------------- your game so far
ROWS = (("elims", "Eliminations"), ("wipes", "Team wipes"), ("cashouts", "Cashouts"),
        ("steals", "Steals"), ("best", "Best multi kill"), ("cash", "Cash earned"))


def render_box(stats, scale=1.0):
    s = scale * 2
    f = _fonts(s)
    pad, gap = int(10 * s), int(6 * s)
    ic = int(14 * s)
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
        ic = int(12 * s)
        card.alpha_composite(icon(k, ic, GOLD if k == "cash" else CYAN), (tx + int(8 * s), ty + int(8 * s)))
        d.text((tx + int(8 * s) + ic + int(5 * s), ty + int(9 * s)), lab, font=f_l, fill=HAZE)
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
