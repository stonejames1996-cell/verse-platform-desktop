"""
League of Legends live companion: everything Verse shows during and after a League match.

  * Objective timers: a small strip on the right that counts down Dragon, Elder, Baron and inhibitor
    respawns. It only uses the kill announcements every player sees (the game's event feed).
  * While you're dead (or on Alt+Shift+I): one panel with your game so far (CS per minute, kill share
    and vision vs your own average), your items' gold vs your lane opponent, and counter item ideas.
  * When the game ends: a match summary card, a Windows notification, and the numbers saved with the
    match so the My clips match card can show them next to that game's highlights.

Riot's rules (developer policy, League): only info the player can already see in game, your own stats
are fine, no enemy cooldowns, no win rates, never "do this". Everything here keeps to that.

Data: the Live Client Data API on https://127.0.0.1:2999 (read only, made by Riot for tools like this),
Data Dragon for names and pictures (lol_items.GameData), and your own past games, kept on this PC in
lol_history.json.
"""

import json
import logging
import os
import threading
import time

from PIL import Image, ImageDraw, ImageFilter

import highlights
import lol_items
import opgg

log = logging.getLogger("verse.lol")

DRAGON_RESPAWN = 300
ELDER_RESPAWN = 360
BARON_RESPAWN = 360
INHIB_RESPAWN = 300
UP_FOR = 12            # keep "Baron is up" on the strip for this many seconds
RIFT_MODES = {"CLASSIC", "SWIFTPLAY"}
LANES = {"L1": "top", "C1": "mid", "R1": "bot"}


def me_in(game):
    active = game.get("activePlayer") or {}
    mine = highlights._names(active.get("riotId"), active.get("summonerName"))
    return next((p for p in game.get("allPlayers") or []
                 if highlights._names(p.get("riotId"), p.get("summonerName"), p.get("riotIdGameName")) & mine), None)


def clock(sec):
    sec = max(0, int(round(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


# ---------------------------------------------------------------- objective timers
class ObjectiveTimers:
    """Works out respawn countdowns from the match's event feed (game clock seconds)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.seen = -1
        self.dragons = {"ORDER": 0, "CHAOS": 0}
        self.timers = {}     # key -> {"label", "at" (game time it's back), "kind"}

    def update(self, game, me_team):
        events = ((game.get("events") or {}).get("Events")) or []
        if events and events[-1].get("EventID", 0) < self.seen:
            self.reset()    # a new match
        teams = {}
        for p in game.get("allPlayers") or []:
            for n in highlights._names(p.get("riotId"), p.get("summonerName"), p.get("riotIdGameName")):
                teams[n] = p.get("team")
        for e in events:
            if e.get("EventID", -1) <= self.seen:
                continue
            self.seen = e.get("EventID", self.seen)
            name, t = e.get("EventName"), float(e.get("EventTime", 0))
            killer_team = next((teams[n] for n in highlights._names(e.get("KillerName")) if n in teams), None)
            if name == "DragonKill":
                elder = str(e.get("DragonType", "")).lower() == "elder"
                if not elder and killer_team in self.dragons:
                    self.dragons[killer_team] += 1
                soul = max(self.dragons.values()) >= 4
                if elder or soul:
                    self.timers["dragon"] = {"label": "Elder Dragon", "at": t + ELDER_RESPAWN, "kind": "elder"}
                else:
                    self.timers["dragon"] = {"label": "Dragon", "at": t + DRAGON_RESPAWN, "kind": "dragon"}
            elif name == "BaronKill":
                self.timers["baron"] = {"label": "Baron", "at": t + BARON_RESPAWN, "kind": "baron"}
            elif name == "InhibKilled":
                key = str(e.get("InhibKilled", ""))          # e.g. Barracks_T2_L1
                parts = key.split("_")
                side = "ORDER" if "T1" in parts else "CHAOS" if "T2" in parts else ""
                lane = next((LANES[x] for x in parts if x in LANES), "")
                whose = "Our" if side == me_team else "Their"
                self.timers["inhib:" + key] = {"label": f"{whose} {lane} inhib".replace("  ", " "),
                                              "at": t + INHIB_RESPAWN, "kind": "inhib_ours" if whose == "Our" else "inhib"}
            elif name == "InhibRespawned":
                self.timers.pop("inhib:" + str(e.get("InhibRespawned", "")), None)

    def active(self, now):
        """[(label, text, kind)] soonest first; finished ones show "up" for a few seconds."""
        out = []
        for key, tm in list(self.timers.items()):
            left = tm["at"] - now
            if left < -UP_FOR:
                del self.timers[key]
                continue
            if key.startswith("inhib:") and left <= 0:
                del self.timers[key]       # inhibitors just come back, nothing to announce
                continue
            out.append((left, tm["label"], "up" if left <= 0 else clock(left), tm["kind"]))
        return [(label, text, kind) for _, label, text, kind in sorted(out)]


DOTS = {"dragon": (251, 146, 60), "elder": (94, 234, 212), "baron": (192, 132, 252),
        "inhib": (148, 163, 184), "inhib_ours": (248, 113, 113)}


def bench_rows(nums, avg, gpm, opp_level, spark):
    """The benchmark lines, like "CSM +0.6 / 6.8": yours, then your average (or your lane opponent's level)."""
    avg = avg or {}

    def row(label, cur, base, fmt, diff=False, spark_pts=None):
        if cur is None:
            return None
        state = None
        if base:
            state = "up" if cur > base * 1.04 else "down" if cur < base * 0.96 else None
        if diff and base:
            d = cur - base
            value = f"{'+' if d >= 0 else '-'}{fmt(abs(d))}"
        else:
            value = fmt(cur)
        return {"label": label, "value": value, "base": fmt(base) if base else "", "state": state, "spark": spark_pts}
    rows = [
        row("CSM", nums.get("cs_min"), avg.get("cs_min"), lambda v: f"{v:.1f}", diff=True, spark_pts=spark),
        row("GPM", gpm, avg.get("gpm"), lambda v: f"{v:.0f}"),
        row("KP%", None if nums.get("kp") is None else nums["kp"] * 100,
            None if avg.get("kp") is None else avg["kp"] * 100, lambda v: f"{v:.0f}"),
        row("KDA", nums.get("kda"), avg.get("kda"), lambda v: f"{v:.1f}"),
        row("LVL", nums.get("level"), opp_level, lambda v: f"{v:.0f}"),
    ]
    return [r for r in rows if r]


def render_strip(bench, rows, scale=1.0):
    """The box on the right: your benchmarks on top (vs your own average), objective timers under them."""
    return render_timers(rows, scale, bench)


def render_timers(rows, scale=1.0, bench=None):
    """The small timers strip: a dot, the objective and its countdown on each line."""
    bench = bench or []
    from overlay import HAZE, WHITE
    from watermark import _font, _spaced
    s = scale * 2
    pad, gap = int(10 * s), int(5 * s)
    f_label = _font("Inter-SemiBold.otf", int(7.5 * s))
    f_row = _font("Inter-SemiBold.otf", int(10.5 * s))
    f_time = _font("InterDisplay-Bold.otf", int(11 * s))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lh = lambda f: sum(f.getmetrics())
    name_w = max([probe.textlength(r[0], font=f_row) for r in rows] or [0])
    time_w = max([probe.textlength(r[1], font=f_time) for r in rows] or [0])
    dot = int(6 * s)
    w = int(pad * 2 + dot + int(7 * s) + name_w + int(14 * s) + time_w)
    w = max(w, int(150 * s))
    spark_w = int(34 * s)
    if bench:
        lab_w = max(probe.textlength(b["label"], font=f_row) for b in bench)
        val_w = max(probe.textlength(b["value"], font=f_time) for b in bench)
        base_w = max(probe.textlength(("/ " + b["base"]) if b["base"] else "", font=f_row) for b in bench)
        w = max(w, int(pad * 2 + lab_w + int(10 * s) + val_w + int(5 * s) + base_w + int(8 * s) + spark_w))
    h = pad
    if bench:
        h += lh(f_label) + int(4 * s) + len(bench) * (lh(f_row) + gap) - gap + (int(12 * s) if rows else 0)
    if rows:
        h += lh(f_label) + int(4 * s) + len(rows) * (lh(f_row) + gap) - gap
    h += pad
    r = int(10 * s)
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=(16, 16, 20, 214), outline=(255, 255, 255, 30),
                        width=max(1, int(s)))
    y = pad
    if bench:
        UP, DOWN = (52, 211, 153, 255), (251, 191, 36, 255)
        _spaced(d, (pad, y), "VERSE PLATFORM", f_label, HAZE, 1.4 * s)
        y += lh(f_label) + int(4 * s)
        lab_w = max(probe.textlength(b["label"], font=f_row) for b in bench)
        val_w = max(probe.textlength(b["value"], font=f_time) for b in bench)
        for b in bench:
            d.text((pad, y), b["label"], font=f_row, fill=HAZE)
            vx = pad + lab_w + int(10 * s)
            col = UP if b["state"] == "up" else DOWN if b["state"] == "down" else WHITE
            d.text((vx, y - int(1 * s)), b["value"], font=f_time, fill=col)
            if b["base"]:
                d.text((vx + val_w + int(5 * s), y), "/ " + b["base"], font=f_row, fill=(140, 144, 156, 255))
            pts = b.get("spark") or []
            if len(pts) >= 2:   # a tiny line of how it has gone this game
                lo, hi = min(pts), max(pts)
                span = (hi - lo) or 1
                x1, y1, hh = w - pad - spark_w, y + int(2 * s), lh(f_row) - int(4 * s)
                line = [(x1 + i * spark_w / (len(pts) - 1), y1 + hh - (v - lo) / span * hh) for i, v in enumerate(pts)]
                d.line(line, fill=(34, 211, 238, 255), width=max(1, int(1.2 * s)), joint="curve")
                ex, ey = line[-1]
                d.ellipse((ex - 2 * s, ey - 2 * s, ex + 2 * s, ey + 2 * s), fill=(34, 211, 238, 255))
            y += lh(f_row) + gap
        y += -gap + (int(12 * s) if rows else 0)
        if rows:
            d.line([(pad, y - int(6 * s)), (w - pad, y - int(6 * s))], fill=(255, 255, 255, 26), width=max(1, int(s)))
    if rows:
        _spaced(d, (pad, y), "OBJECTIVES", f_label, HAZE, 1.4 * s)
        y += lh(f_label) + int(4 * s)
    for label, text, kind in rows:
        cy = y + lh(f_row) // 2
        d.ellipse((pad, cy - dot // 2, pad + dot, cy + dot // 2), fill=DOTS.get(kind, (200, 200, 200)) + (255,))
        d.text((pad + dot + int(7 * s), y), label, font=f_row, fill=WHITE)
        tw = probe.textlength(text, font=f_time)
        d.text((w - pad - tw, y - int(1 * s)), text, font=f_time,
               fill=(52, 211, 153, 255) if text == "up" else WHITE)
        y += lh(f_row) + gap
    m = int(8 * s)
    full = Image.new("RGBA", (w + m * 2, h + m * 2), (0, 0, 0, 0))
    sh = Image.new("L", full.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((m, m + int(2 * s), m + w, m + h + int(2 * s)), radius=r, fill=110)
    full.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(int(5 * s))))
    full.alpha_composite(card, (m, m))
    return full.resize((max(1, full.width // 2), max(1, full.height // 2)), Image.LANCZOS)


# ---------------------------------------------------------------- your numbers
def live_numbers(game, me):
    """CS per minute, kill share and vision per minute right now (None until 3 minutes in)."""
    minutes = float((game.get("gameData") or {}).get("gameTime", 0)) / 60
    if not me or minutes < 3:
        return None
    sc = me.get("scores") or {}
    team_kills = sum((p.get("scores") or {}).get("kills", 0) for p in game.get("allPlayers") or []
                     if p.get("team") == me.get("team"))
    involved = sc.get("kills", 0) + sc.get("assists", 0)
    return {"cs_min": sc.get("creepScore", 0) / minutes,
            "kp": min(1.0, involved / team_kills) if team_kills else None,
            "vision_min": float(sc.get("wardScore", 0)) / minutes,
            "cs": sc.get("creepScore", 0), "minutes": minutes,
            "kills": sc.get("kills", 0), "deaths": sc.get("deaths", 0), "assists": sc.get("assists", 0),
            "kda": involved / max(1, sc.get("deaths", 0)), "level": me.get("level", 0),
            "vision": float(sc.get("wardScore", 0))}


def gold_per_min(gd, game, me, minutes):
    """Rough gold per minute: what your items are worth plus the gold in your pocket. League doesn't share
    gold earned, so selling items or using potions makes this read a little low."""
    if not me or minutes < 3:
        return None
    items = sum(gd.gold(int(i.get("itemID", 0))) * max(1, int(i.get("count", 1) or 1))
                for i in me.get("items") or [] if i.get("itemID"))
    pocket = float((game.get("activePlayer") or {}).get("currentGold", 0) or 0)
    return (items + pocket) / minutes


class History:
    """Your finished League games on this PC, for "vs your average"."""

    KEEP = 200

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "lol_history.json")
        self.lock = threading.Lock()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.games = json.load(f)
        except (OSError, ValueError):
            self.games = []

    def add(self, rec):
        with self.lock:
            self.games = [g for g in self.games if g.get("id") != rec.get("id")] + [rec]
            self.games = self.games[-self.KEEP:]
            try:
                with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(self.games, f)
                os.replace(self.path + ".tmp", self.path)
            except OSError:
                log.warning("Couldn't save League history", exc_info=True)

    def averages(self, role, rift, exclude=None):
        """Averages over your last 20 games of the same kind (same role when there are 5 or more)."""
        with self.lock:
            same = [g for g in self.games if g.get("rift") == rift and g.get("id") != exclude and g.get("minutes", 0) >= 10]
        by_role = [g for g in same if role and g.get("role") == role]
        pool = (by_role if len(by_role) >= 5 else same)[-20:]
        if len(pool) < 3:
            return None
        avg = lambda k: sum(g[k] for g in pool if g.get(k) is not None) / max(1, sum(1 for g in pool if g.get(k) is not None))
        def curve(key):   # your usual value at each minute, from games that lasted that long (3 or more)
            out = []
            for i in range(60):
                at = [g[key][i] for g in pool if len(g.get(key) or []) > i]
                if len(at) < 3:
                    break
                out.append(round(sum(at) / len(at), 1))
            return out
        return {"cs_min": avg("cs_min"), "kp": avg("kp"), "vision_min": avg("vision_min"),
                "gpm": avg("gpm"), "kda": avg("kda"), "games": len(pool),
                "same_role": len(by_role) >= 5, "cs_curve": curve("cs_at"), "vision_curve": curve("vision_at")}


def stat_tiles(now, avg):
    """The three "YOUR GAME" tiles."""
    def vs(cur, base, fmt):
        if base is None or cur is None:
            return "", None
        diff = cur - base
        same = abs(diff) < max(0.04 * base, 0.05)
        return (f"avg {fmt(base)}" + ("" if same else " ▲" if diff > 0 else " ▼"),
                None if same else diff > 0)
    tiles = []
    for key, label, fmt in (("cs_min", "CS per min", lambda v: f"{v:.1f}"),
                            ("kp", "Kill share", lambda v: f"{round(v * 100)}%"),
                            ("vision_min", "Vision per min", lambda v: f"{v:.2f}")):
        cur = now.get(key)
        text, up = vs(cur, (avg or {}).get(key), fmt)
        tiles.append({"value": fmt(cur) if cur is not None else "-", "label": label,
                      "vs": text or ("building your average" if not avg else ""), "up": up})
    return tiles


def lane_gold(gd, game, me):
    """Your items' gold vs the enemy in your position (needs positions, so Summoner's Rift)."""
    pos = (me or {}).get("position") or ""
    if not pos or pos.upper() in ("NONE", "INVALID"):
        return None
    opp = next((p for p in game.get("allPlayers") or [] if p.get("team") != me.get("team") and p.get("position") == pos), None)
    if not opp:
        return None

    def value(p):
        return sum(gd.gold(int(i.get("itemID", 0))) * max(1, int(i.get("count", 1) or 1))
                   for i in p.get("items") or [] if i.get("itemID"))
    k1, _ = gd.champ(me.get("rawChampionName"), me.get("championName"))
    k2, _ = gd.champ(opp.get("rawChampionName"), opp.get("championName"))
    return {"me": value(me), "them": value(opp), "me_key": k1, "them_key": k2,
            "them_name": opp.get("championName") or k2}


# ---------------------------------------------------------------- post match analysis
PHASES = (("Lane phase", 0, 14), ("Mid game", 14, 25), ("Late game", 25, 999))


def phase_rates(cs, upto=None):
    """CS per minute in each phase, from a CS-at-each-minute list. None for a phase the game didn't reach."""
    out = []
    end = len(cs) - 1
    for name, a, b in PHASES:
        b2 = min(b, end if upto is None else min(end, upto))
        if b2 - a < 3:
            out.append(None)
            continue
        out.append(round((cs[b2] - cs[a]) / (b2 - a), 2))
    return out


def analyse(tl, deaths, avg, nums, opp_name, me_name):
    """A few plain sentences about the game, plus the numbers the My clips chart needs.
    tl: {"cs": [...], "opp_cs": [...], "level": [...], "opp_level": [...]} one entry per game minute."""
    cs, opp = tl.get("cs") or [], tl.get("opp_cs") or []
    avg = avg or {}
    curve = avg.get("cs_curve") or []
    tips = []
    mine = phase_rates(cs) if len(cs) > 3 else [None, None, None]
    usual = phase_rates(curve, upto=len(cs) - 1) if len(curve) > 3 else [None, None, None]

    # farming by phase vs your usual
    gaps = [(m - u, name, m, u) for (name, _, _), m, u in zip(PHASES, mine, usual) if m is not None and u]
    if gaps:
        worst = min(gaps)
        best = max(gaps)
        if worst[0] < -0.6:
            tips.append({"cat": "farming", "kind": "down", "text": f"Your farming dropped in the {worst[1].lower()}: "
                         f"{worst[2]:.1f} CS a minute, your usual is {worst[3]:.1f}."})
        if best[0] > 0.6 and best is not worst:
            tips.append({"cat": "farming", "kind": "up", "text": f"Great farming in the {best[1].lower()}: "
                         f"{best[2]:.1f} CS a minute, up from your usual {best[3]:.1f}."})

    # your lane opponent (same CS they show on Tab)
    if opp_name and len(opp) > 10 and len(cs) > 10:
        d10 = cs[10] - opp[10]
        word = "ahead of" if d10 > 0 else "behind"
        if abs(d10) >= 8:
            tips.append({"cat": "farming", "kind": "up" if d10 > 0 else "down",
                         "text": f"At 10 minutes you were {abs(d10)} CS {word} {opp_name}."})
        end = min(len(cs), len(opp)) - 1
        dend = cs[end] - opp[end]
        if end > 15 and abs(dend - d10) >= 15:
            turn = next((i for i in range(10, end + 1) if (cs[i] - opp[i]) * (1 if dend > 0 else -1) > 0
                         and (cs[i - 1] - opp[i - 1]) * (1 if dend > 0 else -1) <= 0), None)
            when = f" from about {turn} minutes" if turn and turn > 10 else ""
            tips.append({"cat": "farming", "kind": "up" if dend > d10 else "down",
                         "text": f"{'You pulled ahead of' if dend > d10 else opp_name + ' out-farmed'} "
                                 f"{opp_name if dend > d10 else 'you'}{when}: "
                                 f"{abs(dend)} CS {'ahead' if dend > 0 else 'behind'} by the end."})
    lv, olv = tl.get("level") or [], tl.get("opp_level") or []
    # (levels count as fights)
    if opp_name and len(lv) > 15 and len(olv) > 15 and abs(lv[15] - olv[15]) >= 2:
        d = lv[15] - olv[15]
        tips.append({"cat": "combat", "kind": "up" if d > 0 else "down",
                     "text": f"At 15 minutes you were {abs(d)} levels {'above' if d > 0 else 'below'} {opp_name}."})

    # deaths: early ones and clusters
    if deaths:
        first = deaths[0]
        if first < 8 * 60:
            tips.append({"cat": "combat", "kind": "down", "text": f"First death at {clock(first)}. An early death costs a lot of lane gold."})
        for i in range(len(deaths) - 2):
            if deaths[i + 2] - deaths[i] <= 6 * 60:
                tips.append({"cat": "combat", "kind": "down", "text": f"3 deaths in a short spell, between {clock(deaths[i])} and {clock(deaths[i + 2])}."})
                break
    elif nums.get("minutes", 0) >= 15:
        tips.append({"cat": "combat", "kind": "up", "text": "No deaths all game. Nice."})

    # fights and vision vs your usual
    if nums.get("kp") is not None and avg.get("kp"):
        if nums["kp"] >= avg["kp"] + 0.12:
            tips.append({"cat": "combat", "kind": "up", "text": f"You were in {round(nums['kp'] * 100)}% of your team's kills, "
                         f"more than your usual {round(avg['kp'] * 100)}%."})
        elif nums["kp"] <= avg["kp"] - 0.12:
            tips.append({"cat": "combat", "kind": "down", "text": f"You were in {round(nums['kp'] * 100)}% of your team's kills, "
                         f"less than your usual {round(avg['kp'] * 100)}%."})
    if nums.get("vision_min") and avg.get("vision_min"):
        if nums["vision_min"] < avg["vision_min"] * 0.75:
            tips.append({"cat": "vision", "kind": "down", "text": f"Less vision than usual: {nums['vision_min']:.2f} a minute, "
                         f"your usual is {avg['vision_min']:.2f}."})
        elif nums["vision_min"] > avg["vision_min"] * 1.25:
            tips.append({"cat": "vision", "kind": "up", "text": f"More vision than usual: {nums['vision_min']:.2f} a minute."})
    # scores out of 100 for each tab: 50 is your usual game (or a typical one before you have an average)
    def score(ratio):
        return int(max(5, min(99, round(50 + (min(ratio, 2.0) - 1) * 100))))

    def rating(sc):
        return "Poor" if sc < 35 else "Fair" if sc < 55 else "Good" if sc < 75 else "Great"
    cs_min = nums.get("cs_min") or (cs[-1] / max(1, len(cs) - 1) if cs else 0)
    if avg.get("cs_min"):
        f_ratio, f_vs = cs_min / avg["cs_min"], "your usual"
    elif opp_name and opp and opp[-1]:
        f_ratio, f_vs = cs[-1] / opp[-1], opp_name
    else:
        f_ratio, f_vs = cs_min / 7.0, "a typical game"
    kp, kda = nums.get("kp"), nums.get("kda")
    kp_r = kp / (avg.get("kp") or 0.5) if kp is not None else 1.0
    kda_r = (kda or 0) / (avg.get("kda") or 3.0)
    vis = nums.get("vision_min") or 0
    v_r = vis / (avg.get("vision_min") or 0.8)
    vis_tl, usual_vis = tl.get("vision") or [], (avg.get("vision_curve") or [])[:len(tl.get("vision") or [])]

    # the weakest phase gets shaded on the farming chart
    weak = None
    below = [(m - u, a_, b_) for (name, a_, b_), m, u in zip(PHASES, mine, usual) if m is not None and u and m < u * 0.92]
    if below:
        _, a_, b_ = min(below)
        weak = [a_, min(b_, len(cs) - 1)]

    def headline(cat):
        mine_tips = [t for t in tips if t["cat"] == cat]
        return (next((t for t in mine_tips if t["kind"] == "down"), None) or (mine_tips[0] if mine_tips else None))
    bars_f = [{"name": name, "you": m, "usual": u, "fmt": "1"} for (name, _, _), m, u in zip(PHASES, mine, usual) if m is not None]
    bars_c = [b for b in (
        {"name": "Kill share", "you": round(kp * 100) if kp is not None else None,
         "usual": round(avg["kp"] * 100) if avg.get("kp") else None, "fmt": "%"},
        {"name": "K/D/A", "you": round(kda, 1) if kda is not None else None,
         "usual": round(avg["kda"], 1) if avg.get("kda") else None, "fmt": "1"},
        {"name": "Deaths", "you": len(deaths), "usual": None, "fmt": "0", "lower": True}) if b["you"] is not None]
    bars_v = [{"name": "Vision a min", "you": round(vis, 2), "usual": round(avg["vision_min"], 2) if avg.get("vision_min") else None, "fmt": "2"},
              {"name": "Vision score", "you": vis_tl[-1] if vis_tl else round(nums.get("vision", 0)), "usual": None, "fmt": "0"}]
    cats = {
        "farming": {"title": "Farming", "score": score(f_ratio), "vs": f_vs, "bars": bars_f, "headline": headline("farming"),
                    "chart": "CS at every minute of the game",
                    "lines": [{"name": "You", "pts": cs, "style": "you"}]
                    + ([{"name": opp_name, "pts": opp, "style": "opp"}] if opp_name and any(opp) else [])
                    + ([{"name": "Your usual", "pts": curve[:len(cs)], "style": "usual"}] if len(curve) > 1 else []),
                    "weak": weak},
        "combat": {"title": "Combat", "score": score((kp_r + kda_r) / 2), "vs": "your usual" if avg.get("kp") else "a typical game",
                   "bars": bars_c, "headline": headline("combat"), "chart": "Kills you were in vs your team's kills",
                   "lines": [{"name": "Your team's kills", "pts": tl.get("team_kills") or [], "style": "opp"},
                             {"name": "Kills you were in", "pts": tl.get("ka") or [], "style": "you"}],
                   "weak": None},
        "vision": {"title": "Vision", "score": score(v_r), "vs": "your usual" if avg.get("vision_min") else "a typical game",
                   "bars": bars_v, "headline": headline("vision"), "chart": "Vision score over the game",
                   "lines": [{"name": "You", "pts": vis_tl, "style": "you"}]
                   + ([{"name": "Your usual", "pts": usual_vis, "style": "usual"}] if len(usual_vis) > 1 else []),
                   "weak": None},
    }
    for c in cats.values():
        c["rating"] = rating(c["score"])
    return {
        "tips": tips[:8], "cats": cats,
        "cs": cs, "opp_cs": opp if opp_name else [], "usual_cs": curve[:len(cs)], "opp_name": opp_name or "",
        "deaths": [round(t / 60, 2) for t in deaths],
        "phases": [{"name": name, "you": m, "usual": u} for (name, _, _), m, u in zip(PHASES, mine, usual)],
    }


def add_rank(analysis, nums, ctx, champ):
    """Adds the OP.GG comparisons to the analysis: your rank, KDA vs players at your rank on this champion,
    and CS / gold vs the top players on this champion."""
    if not analysis or not ctx:
        return analysis
    cats = analysis.get("cats") or {}
    rank, at_tier, top = ctx.get("rank"), ctx.get("at_tier"), ctx.get("top")
    if rank:
        analysis["rank"] = rank
    tips = analysis.setdefault("tips", [])
    kda = nums.get("kda")
    if at_tier and kda is not None and "combat" in cats:
        who = f"{at_tier['tier']} {champ}" if at_tier.get("tier") != "all ranks" else champ
        cats["combat"]["bars"].append({"name": f"KDA vs {who}", "you": round(kda, 1), "usual": round(at_tier["kda"], 1), "fmt": "1"})
        better = kda >= at_tier["kda"]
        tips.append({"cat": "combat", "kind": "up" if better else "down",
                     "text": f"Your KDA of {kda:.1f} was {'above' if better else 'below'} the {at_tier['kda']:.1f} average "
                             f"for {who} players."})
        cats["combat"]["vs_rank"] = who
    if top and nums.get("cs_min") and "farming" in cats:
        cats["farming"]["bars"].append({"name": f"Top {champ} players", "you": round(nums["cs_min"], 1),
                                        "usual": round(top["cs_min"], 1), "fmt": "1"})
        tips.append({"cat": "farming", "kind": "down" if nums["cs_min"] < top["cs_min"] * 0.85 else "up",
                     "text": f"The top {champ} players average {top['cs_min']:.1f} CS a minute. You had {nums['cs_min']:.1f}."})
    return analysis


# ---------------------------------------------------------------- match summary card
def render_summary(gd, s, scale=1.0):
    """End of game card: result, champion, K/D/A, the three numbers vs average, highlights saved."""
    from overlay import HAZE, SIGNAL, WHITE, _logo
    from watermark import _font, _spaced
    k = scale * 2
    pad = int(16 * k)
    f_label = _font("Inter-SemiBold.otf", int(9.5 * k))
    f_title = _font("InterDisplay-Bold.otf", int(17 * k))
    f_row = _font("Inter-SemiBold.otf", int(11 * k))
    f_small = _font("Inter-SemiBold.otf", int(9.5 * k))
    lh = lambda f: sum(f.getmetrics())
    face = int(40 * k)
    w = int(340 * k)
    lines = [f"{s['kills']} / {s['deaths']} / {s['assists']}   ·   {s['cs']} CS ({s['cs_min']:.1f} a min)"]
    if s.get("kp") is not None:
        lines.append(f"Kill share {round(s['kp'] * 100)}%   ·   Vision {s['vision']:.0f}")
    if s.get("better"):
        lines.append("Better than your average: " + ", ".join(s["better"]))
    clips = s.get("clips", 0)
    foot = (f"{clips} highlight{'s' if clips != 1 else ''} saved. Open Verse to post them."
            if clips else "Open Verse to see this game's clips.")
    h = pad + max(face, lh(f_label) + lh(f_title)) + int(10 * k) + len(lines) * (lh(f_row) + int(3 * k)) \
        + int(8 * k) + lh(f_small) + pad
    r = int(14 * k)
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    body = Image.new("RGBA", (w, h))
    bd = ImageDraw.Draw(body)
    for yy in range(h):
        c = int(24 - 12 * yy / max(1, h - 1))
        bd.line([(0, yy), (w, yy)], fill=(c, c, c + 4, 242))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    card.paste(body, (0, 0), mask)
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, outline=(255, 255, 255, 34), width=max(1, int(k)))
    win = s.get("result") == "Win"
    accent = (52, 211, 153, 255) if win else (248, 113, 113, 255) if s.get("result") else SIGNAL
    d.rounded_rectangle((int(5 * k), r, int(8 * k), h - r), radius=int(2 * k), fill=accent)
    x0, y = pad + int(4 * k), pad
    im = gd.champ_icon(s.get("champion_key"), face) if s.get("champion_key") else None
    if im is not None:
        m = Image.new("L", (face, face), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, face - 1, face - 1), radius=int(9 * k), fill=255)
        card.paste(im, (x0, y), m)
    else:
        lg = _logo(face)
        if lg:
            card.alpha_composite(lg, (x0, y))
    tx = x0 + face + int(12 * k)
    _spaced(d, (tx, y + int(1 * k)), "MATCH SUMMARY  ·  VERSE PLATFORM", f_label, HAZE, 1.6 * k)
    title = (s.get("result") or "Game over") + (f" as {s['champion']}" if s.get("champion") else "")
    d.text((tx, y + lh(f_label) + int(1 * k)), title, font=f_title, fill=WHITE)
    y += max(face, lh(f_label) + lh(f_title)) + int(10 * k)
    for line in lines:
        d.text((x0, y), line, font=f_row, fill=WHITE if not line.startswith("Better") else (52, 211, 153, 255))
        y += lh(f_row) + int(3 * k)
    y += int(8 * k)
    d.text((x0, y), foot, font=f_small, fill=HAZE)
    m = int(12 * k)
    full = Image.new("RGBA", (w + m * 2, h + m * 2), (0, 0, 0, 0))
    sh = Image.new("L", full.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((m, m + int(3 * k), m + w, m + h + int(3 * k)), radius=r, fill=130)
    full.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(int(7 * k))))
    full.alpha_composite(card, (m, m))
    return full.resize((max(1, full.width // 2), max(1, full.height // 2)), Image.LANCZOS)


# ---------------------------------------------------------------- the companion
class LeagueCompanion:
    """One loop, once a second during a League match, driving all of the above."""

    GAME = "League of Legends"

    def __init__(self, get_cfg, is_playing, overlay, strip, data_dir, get_match=lambda: None,
                 on_summary=lambda m: None, notify=lambda t, x: None, count_clips=lambda match_id: 0, get=None):
        self.get_cfg, self.is_playing = get_cfg, is_playing
        self.overlay, self.strip = overlay, strip      # strip: a second overlay window for the timers
        self.gd = lol_items.GameData(data_dir)
        self.history = History(data_dir)
        self.get = get or highlights._get
        self.get_match, self.on_summary, self.notify, self.count_clips = get_match, on_summary, notify, count_clips
        self.timers = ObjectiveTimers()
        self.dead = False
        self.asked = 0.0
        self.strip_shown = ""
        self.spark = []          # CS per minute, sampled once a game minute, for the little line
        self.spark_min = -1
        self.last_gpm = None
        self.gd_tried = 0.0
        self.tl = None           # this game, one sample a minute, for the post match analysis
        self.opgg = opgg.OPGG(data_dir)
        self.ctx = None          # OP.GG: your rank, your champion at your rank, top players (fetched at game start)
        self.ctx_key = None
        self.ended = set()
        self.last_game = None

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="league-live").start()

    def cfg(self, key, default=True):
        return bool(self.get_cfg().get(key, default))

    def show_now(self, *_):
        """Alt+Shift+I: the panel for a few seconds."""
        self.asked = time.time()

    def _loop(self):
        while True:
            try:
                if self.is_playing(self.GAME):
                    self._tick()
                else:
                    self._idle()
            except Exception:
                log.debug("league live poll", exc_info=True)
            time.sleep(1)

    def _idle(self):
        self.dead = False
        self._strip([])
        if self.last_game:   # the game closed before we saw "GameEnd" (a remake, or a crash)
            self.last_game = None
            self.timers.reset()

    def _strip(self, rows, bench=None):
        bench = bench or []
        key = "|".join(f"{a}{b}" for a, b, _ in rows) + "#" + "|".join(
            f"{b['label']}{b['value']}{b['base']}{len(b.get('spark') or [])}" for b in bench)
        if key == self.strip_shown:
            return
        self.strip_shown = key
        if not rows and not bench:
            self.strip.hide_static()
        else:
            self.strip.show_static(render_strip(bench, rows, self.strip.scale()), place="right")

    def _rank_context(self, game, me):
        """Once a game, in the background: your rank and the OP.GG comparisons for your champion."""
        if not self.cfg("lol_opgg"):
            return
        riot = (game.get("activePlayer") or {}).get("riotId") or me.get("riotId") or ""
        key = (riot, me.get("championName"), me.get("position"))
        if key == self.ctx_key:
            return
        self.ctx_key, self.ctx = key, {}
        ctx = self.ctx

        def fetch():
            region = opgg.league_region()
            ctx["region"] = region
            champ, pos = me.get("championName", ""), me.get("position", "")
            rank = self.opgg.profile(riot, region) if region else None
            if rank:
                ctx["rank"] = rank
            at = self.opgg.champion_at_tier(champ, pos, rank["tier"] if rank else None)
            if at:
                ctx["at_tier"] = at
            top = self.opgg.top_players(champ, region) if region else None
            if top:
                ctx["top"] = top
            log.info("OP.GG: region %s, rank %s, %s", region or "unknown", (rank or {}).get("text", "unranked"),
                     "champion stats ready" if at or top else "no champion stats")
        threading.Thread(target=fetch, daemon=True, name="opgg").start()

    def _real_numbers(self, match_id, summary, riot, started, champion):
        """After the game: OP.GG's real gold and damage once it has the match (tries for about 20 minutes)."""
        region = (self.ctx or {}).get("region")
        if not (self.cfg("lol_opgg") and region and match_id):
            return

        def wait():
            for delay in (90, 180, 300, 600):
                time.sleep(delay)
                real = self.opgg.recent_game(riot, region, started, champion)
                if real:
                    summary["real"] = real
                    self.on_summary({"id": match_id, "summary": summary})
                    log.info("OP.GG has the match: %s gold, %s damage", real.get("gold"), real.get("damage"))
                    return
            log.info("OP.GG didn't have the match yet, leaving gold and damage out")
        threading.Thread(target=wait, daemon=True, name="opgg-after").start()

    def _sample(self, game, me, now):
        """Once a game minute: your CS and level, and your lane opponent's (both on Tab)."""
        minute = int(now // 60)
        tl = self.tl
        if tl is None or minute < len(tl["cs"]) - 2:
            tl = self.tl = {"cs": [], "opp_cs": [], "level": [], "opp_level": [], "ka": [], "team_kills": [],
                            "vision": [], "opp": ""}
        if minute < len(tl["cs"]):
            return
        pos = me.get("position") or ""
        opp = next((p for p in game.get("allPlayers") or []
                    if pos and p.get("team") != me.get("team") and p.get("position") == pos), None)
        while len(tl["cs"]) <= minute:   # fill any minute we missed (alt-tab, a hitch) with the current value
            tl["cs"].append((me.get("scores") or {}).get("creepScore", 0))
            tl["level"].append(me.get("level", 0))
            tl["opp_cs"].append((opp.get("scores") or {}).get("creepScore", 0) if opp else 0)
            tl["opp_level"].append(opp.get("level", 0) if opp else 0)
            sc = me.get("scores") or {}
            tl["ka"].append(sc.get("kills", 0) + sc.get("assists", 0))
            tl["team_kills"].append(sum((p.get("scores") or {}).get("kills", 0) for p in game.get("allPlayers") or []
                                        if p.get("team") == me.get("team")))
            tl["vision"].append(round(float(sc.get("wardScore", 0)), 1))
        if opp:
            tl["opp"] = opp.get("championName") or ""

    def _bench(self, game, me, now):
        """Your benchmark lines for the box on the right (from 3 minutes in)."""
        nums = live_numbers(game, me)
        if not nums:
            return []
        minute = int(now // 60)
        if minute < self.spark_min:
            self.spark = []      # a new game
        if minute != self.spark_min:
            self.spark_min = minute
            self.spark = (self.spark + [round(nums["cs_min"], 2)])[-30:]
        gpm = gold_per_min(self.gd, game, me, nums["minutes"]) if self.gd.items else None
        self.last_gpm = gpm
        data = game.get("gameData") or {}
        rift = str(data.get("gameMode", "")).upper() in RIFT_MODES
        avg = self.history.averages((me.get("position") or "").upper(), rift)
        pos = me.get("position") or ""
        opp = next((p for p in game.get("allPlayers") or []
                    if pos and p.get("team") != me.get("team") and p.get("position") == pos), None)
        return bench_rows(nums, avg, gpm, (opp or {}).get("level"), self.spark)

    def _tick(self):
        try:
            game = self.get("/allgamedata")
        except Exception:
            self._strip([])
            return   # loading screen, or not in a match
        self.last_game = game
        me = me_in(game)
        data = game.get("gameData") or {}
        mode = str(data.get("gameMode", "")).upper()
        now = float(data.get("gameTime", 0))

        if me:
            self._sample(game, me, now)
            self._rank_context(game, me)

        # the box on the right: benchmarks and objective timers (not in Arena / TFT)
        rows, bench = [], []
        if me and mode not in lol_items.SKIP_MODES:
            if self.cfg("lol_objective_timers"):
                self.timers.update(game, me.get("team"))
                rows = self.timers.active(now)
            if self.cfg("lol_benchmarks"):
                if not self.gd.items and time.time() - self.gd_tried > 60:
                    self.gd_tried = time.time()   # item prices for gold per minute, fetched in the background
                    threading.Thread(target=self.gd.ensure, daemon=True).start()
                bench = self._bench(game, me, now)
        self._strip(rows, bench)

        # the panel while you're dead, or on the shortcut
        if self.cfg("lol_item_ideas"):
            dead = bool(me and me.get("isDead"))
            if dead and not self.dead:
                wait = float(me.get("respawnTimer") or 0)
                if wait >= 4:
                    self._panel(game, me, seconds=min(wait, 75), until=self._still_dead)
            self.dead = dead
        if self.asked and time.time() - self.asked < 3:
            self.asked = 0
            self._panel(game, me, seconds=12, until=None, quiet=False)

        # the end of the game
        events = ((game.get("events") or {}).get("Events")) or []
        end = next((e for e in events if e.get("EventName") == "GameEnd"), None)
        if end and me:
            match = self.get_match() or {}
            key = match.get("id") or f"{me.get('championName')}-{int(now)}"
            if key not in self.ended:
                self.ended.add(key)
                self._finished(game, me, match, str(end.get("Result", "")))

    def _still_dead(self):
        try:
            me = me_in(self.get("/allgamedata"))
            return bool(me and me.get("isDead"))
        except Exception:
            return False

    def _panel(self, game, me, seconds, until, quiet=True):
        if not me:
            return
        ready = self.gd.ensure()
        data = game.get("gameData") or {}
        rift = str(data.get("gameMode", "")).upper() in RIFT_MODES
        extras = {}
        nums = live_numbers(game, me)
        if nums:
            avg = self.history.averages((me.get("position") or "").upper(), rift)
            extras["stats"] = stat_tiles(nums, avg)
        if ready:
            g = lane_gold(self.gd, game, me)
            if g and (g["me"] or g["them"]):
                extras["gold"] = g
        res = lol_items.ideas(self.gd, game) if ready else None
        if not res and not extras:
            if not quiet:
                self.overlay.show("Nothing to show yet", accent="", sub="Give the game a few minutes")
            return
        img = lol_items.render(self.gd, res, self.overlay.scale(), extras)
        log.info("Item ideas shown: %s", " | ".join(r["why"] for r in (res or {}).get("rows", [])) or "stats only")
        self.overlay.show_image(img, seconds=seconds, until=until, place="left", in_clips=True)

    def _finished(self, game, me, match, result):
        nums = live_numbers(game, me) or {}
        data = game.get("gameData") or {}
        rift = str(data.get("gameMode", "")).upper() in RIFT_MODES
        role = (me.get("position") or "").upper()
        result = "Win" if result.lower() == "win" else "Loss" if result else ""
        key, _ = self.gd.champ(me.get("rawChampionName"), me.get("championName")) if self.gd.ensure() else ("", {})
        avg = self.history.averages(role, rift, exclude=match.get("id"))
        better = []
        if avg and nums:
            for k, label in (("cs_min", "CS"), ("kp", "kill share"), ("vision_min", "vision")):
                if nums.get(k) is not None and avg.get(k) and nums[k] > avg[k] * 1.04:
                    better.append(label)
        summary = {
            "result": result, "champion": me.get("championName", ""), "champion_key": key,
            "kills": nums.get("kills", 0), "deaths": nums.get("deaths", 0), "assists": nums.get("assists", 0),
            "cs": nums.get("cs", 0), "cs_min": round(nums.get("cs_min", 0), 2),
            "kp": round(nums["kp"], 3) if nums.get("kp") is not None else None,
            "vision": round(nums.get("vision", 0), 1), "vision_min": round(nums.get("vision_min", 0), 2),
            "role": role, "better": better,
            "avg": {k: round(v, 3) for k, v in (avg or {}).items() if k in ("cs_min", "kp", "vision_min") and v is not None},
        }
        tl = self.tl or {"cs": []}
        names = highlights._names(me.get("riotId"), me.get("summonerName"), me.get("riotIdGameName"))
        deaths = sorted(float(e.get("EventTime", 0)) for e in ((game.get("events") or {}).get("Events") or [])
                        if e.get("EventName") == "ChampionKill" and highlights._names(e.get("VictimName")) & names)
        try:
            summary["analysis"] = add_rank(analyse(tl, deaths, avg, nums, tl.get("opp", ""), me.get("championName", "")),
                                           nums, self.ctx, me.get("championName", ""))
        except Exception:
            log.exception("Post match analysis")
        if nums.get("minutes", 0) >= 10:     # remakes don't count towards your average
            self.history.add({"id": match.get("id") or f"lol-{int(time.time())}", "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                              "rift": rift, "role": role, "champion": summary["champion"], "result": result,
                              "minutes": round(nums.get("minutes", 0), 1), "cs_min": summary["cs_min"],
                              "kp": summary["kp"], "vision_min": summary["vision_min"],
                              "kda": round(nums.get("kda", 0), 2),
                              "gpm": round(self.last_gpm, 1) if self.last_gpm else None,
                              "cs_at": list(tl.get("cs") or [])[:60],
                              "vision_at": list(tl.get("vision") or [])[:60]})
        self.tl = None
        if (self.ctx or {}).get("rank"):
            summary["rank"] = self.ctx["rank"]
        if match.get("id"):
            self.on_summary({"id": match["id"], "summary": summary})
            started = time.time() - float((game.get("gameData") or {}).get("gameTime", 0))
            riot = (game.get("activePlayer") or {}).get("riotId") or me.get("riotId") or ""
            self._real_numbers(match["id"], dict(summary), riot, started, me.get("championName", ""))
        log.info("Match summary: %s %s/%s/%s, %.1f CS a min", result, summary["kills"], summary["deaths"],
                 summary["assists"], summary["cs_min"])
        if not self.cfg("lol_match_summary"):
            return
        summary["clips"] = self.count_clips(match.get("id"))
        try:
            img = render_summary(self.gd, summary, self.overlay.scale())
            self.overlay.show_image(img, seconds=10, until=None, place="top", in_clips=True)
        except Exception:
            log.exception("Match summary card")
        self.notify(f"{result or 'Game over'} as {summary['champion']}",
                    f"{summary['kills']}/{summary['deaths']}/{summary['assists']}, {summary['cs_min']:.1f} CS a min. "
                    "Your match summary and clips are in Verse.")
