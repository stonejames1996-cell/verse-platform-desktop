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


def render_timers(rows, scale=1.0):
    """The small timers strip: a dot, the objective and its countdown on each line."""
    from overlay import HAZE, WHITE
    from watermark import _font, _spaced
    s = scale * 2
    pad, gap = int(10 * s), int(5 * s)
    f_label = _font("Inter-SemiBold.otf", int(7.5 * s))
    f_row = _font("Inter-SemiBold.otf", int(10.5 * s))
    f_time = _font("InterDisplay-Bold.otf", int(11 * s))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lh = lambda f: sum(f.getmetrics())
    name_w = max(probe.textlength(r[0], font=f_row) for r in rows)
    time_w = max(probe.textlength(r[1], font=f_time) for r in rows)
    dot = int(6 * s)
    w = int(pad * 2 + dot + int(7 * s) + name_w + int(14 * s) + time_w)
    w = max(w, int(130 * s))
    h = pad + lh(f_label) + int(4 * s) + len(rows) * (lh(f_row) + gap) - gap + pad
    r = int(10 * s)
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=(16, 16, 20, 214), outline=(255, 255, 255, 30),
                        width=max(1, int(s)))
    _spaced(d, (pad, pad), "OBJECTIVES", f_label, HAZE, 1.4 * s)
    y = pad + lh(f_label) + int(4 * s)
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
            "vision": float(sc.get("wardScore", 0))}


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
        return {"cs_min": avg("cs_min"), "kp": avg("kp"), "vision_min": avg("vision_min"), "games": len(pool),
                "same_role": len(by_role) >= 5}


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

    def _strip(self, rows):
        key = "|".join(f"{a}{b}" for a, b, _ in rows)
        if key == self.strip_shown:
            return
        self.strip_shown = key
        if not rows:
            self.strip.hide_static()
        else:
            self.strip.show_static(render_timers(rows, self.strip.scale()), place="right")

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

        # objective timers (not in Arena / TFT, which have no such objectives)
        if self.cfg("lol_objective_timers") and mode not in lol_items.SKIP_MODES and me:
            self.timers.update(game, me.get("team"))
            self._strip(self.timers.active(now))
        else:
            self._strip([])

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
        if nums.get("minutes", 0) >= 10:     # remakes don't count towards your average
            self.history.add({"id": match.get("id") or f"lol-{int(time.time())}", "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                              "rift": rift, "role": role, "champion": summary["champion"], "result": result,
                              "minutes": round(nums.get("minutes", 0), 1), "cs_min": summary["cs_min"],
                              "kp": summary["kp"], "vision_min": summary["vision_min"]})
        if match.get("id"):
            self.on_summary({"id": match["id"], "summary": summary})
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
