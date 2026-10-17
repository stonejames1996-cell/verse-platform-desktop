"""
Auto highlights: saves a short clip by itself when something worth posting happens.

League of Legends: uses Riot's official Live Client Data API, which the game itself serves on
https://127.0.0.1:2999 during a match. It's read only, made by Riot for tools like this, and
doesn't touch the game, so it's safe with Vanguard. The app reads the match's event feed once a
second and clips the moments ticked in Settings.

Clip length: from a few seconds before the first moment of a play to a few seconds after the last
one (5 and 5 by default). A fight with a kill, then a double, then a triple becomes ONE clip that
covers all of it, named after the best bits, e.g. "Triple kill + Ace".
"""

import json
import logging
import ssl
import threading
import time
import urllib.request

log = logging.getLogger("verse.highlights")

LOL_API = "https://127.0.0.1:2999/liveclientdata"
TEAMFIGHT_WINDOW = 10   # 3 kills or assists within this many seconds counts as a teamfight
SEGMENT_SLACK = 2.5     # the recorder writes 2 second chunks, wait for the last one to finish

# what can be ticked in Settings, with defaults
DEFAULT_EVENTS = {
    "double": True, "triple": True, "quadra": True, "penta": True,
    "first_blood": True, "ace": True, "teamfight": True, "every_kill": False,
    "steal": True, "baron_elder": True, "dragon": False, "structure": False,
    "victory": True, "defeat": False, "death": False,
}
MULTI = {2: ("double", "Double kill", 4), 3: ("triple", "Triple kill", 6),
         4: ("quadra", "Quadra kill", 9), 5: ("penta", "Pentakill", 10)}
OBJECTIVES = {"BaronKill": "Baron", "DragonKill": "Dragon", "HeraldKill": "Herald",
              "HordeKill": "Voidgrubs", "AtakhanKill": "Atakhan"}

# game modes as the live game reports them -> what players call them
MODES = {"CLASSIC": "Summoner's Rift", "ARAM": "ARAM", "KIWI": "ARAM Mayhem", "CHERRY": "Arena", "URF": "URF",
         "ARURF": "ARURF", "ONEFORALL": "One for All", "NEXUSBLITZ": "Nexus Blitz", "ULTBOOK": "Ultimate Spellbook",
         "PRACTICETOOL": "Practice Tool", "TUTORIAL": "Tutorial", "SWIFTPLAY": "Swiftplay", "BRAWL": "Brawl",
         "STRAWBERRY": "Swarm", "DOOMBOTSTEEMO": "Doom Bots", "TFT": "Teamfight Tactics"}


def mode_name(raw, map_number=None):
    raw = str(raw or "").upper()
    if raw in MODES:
        return MODES[raw]
    if map_number == 12:
        return "ARAM"
    return raw.title() or "League"


# Riot's local game API uses its own certificate, so skip verification for this one localhost address
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def _get(path):
    with urllib.request.urlopen(LOL_API + path, timeout=2, context=_ctx) as r:
        return json.load(r)


def _names(*vals):
    out = set()
    for v in vals:
        if v:
            v = str(v).strip().lower()
            out.add(v)
            out.add(v.split("#")[0])
    out.discard("")
    return out


def events_config(cfg):
    ev = dict(DEFAULT_EVENTS)
    ev.update(cfg.get("highlight_events") or {})
    return ev


class LeagueHighlights:
    """Watches the League match and calls save(label, start_time, end_time) after a highlight."""

    GAME = "League of Legends"

    def __init__(self, get_cfg, is_playing, save, clock=time.time, on_match=None, on_death=None):
        self.get_cfg, self.is_playing, self.save, self.clock = get_cfg, is_playing, save, clock
        self.on_match = on_match or (lambda m: None)   # called with the match details as they change
        self.on_death = on_death or (lambda game, t: None)   # death review: called with the wall time of each death
        self._reset()

    def _reset(self):
        self.me = set()
        self.last_id = None
        self.play = None        # {"labels": {key: (rank, text)}, "first": t, "last": t}
        self.involved = []      # wall times of my kills and assists, for teamfights
        self.my_kills = []      # wall times of my kills, so a multi kill clip starts at the first one
        self.saved = 0
        self.offset = None      # wall clock minus game clock
        self.match = None       # {"id", "mode", "champion", "champion_key", "kills"...}
        self.ticks = 0
        self.me_name = ""
        self.players = set()    # every player name in this match, so squad mates can be recognised

    def to_wall(self, game_time):
        """Game clock -> this PC's clock. Both PCs in a match share the game clock, so this lines up
        squad clips exactly even when the two PCs' clocks differ."""
        return None if self.offset is None else self.offset + float(game_time)

    def to_game(self, wall):
        return None if self.offset is None else float(wall) - self.offset

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="highlights").start()

    def _loop(self):
        while True:
            try:
                cfg = self.get_cfg()
                if self.is_playing(self.GAME):
                    self._tick(cfg)
                elif self.me or self.play:
                    self._check_fire(cfg, force_after_game=True)
                    if not self.play:
                        self._reset()
            except Exception:
                log.debug("highlight poll", exc_info=True)
            time.sleep(1)

    # ---------------------------------------------------------------- polling
    def _tick(self, cfg):
        if not self.me:
            try:
                me = _get("/activeplayername")
                players = _get("/playerlist")
            except Exception:
                return  # still loading, or watching a replay or spectating
            mine = [p for p in players if _names(p.get("riotId"), p.get("summonerName")) & _names(me)]
            self.me_name = str(me)
            self.me = _names(me, *[x for p in mine for x in (p.get("riotId"), p.get("riotIdGameName"), p.get("summonerName"))])
            log.info("Watching League highlights for %s", me)
        try:
            stats = _get("/gamestats")
            game_time = float(stats.get("gameTime", 0))
            events = _get("/eventdata").get("Events", [])
            self.offset = self.clock() - game_time
            self._update_match(stats, game_time)
        except Exception:
            events = []
        if self.last_id is None and self.offset is not None:
            # first look at this match: skip anything that happened before we started watching
            self.last_id = max((e.get("EventID", -1) for e in events), default=-1)
        for e in events:
            if self.last_id is not None and e.get("EventID", -1) > self.last_id:
                self.last_id = e["EventID"]
                self._event(e, cfg)
        self._check_fire(cfg)

    def _update_match(self, stats, game_time):
        self.ticks += 1
        if self.match and self.ticks % 5:
            self.match["length"] = int(game_time)
            return
        try:
            players = _get("/playerlist")
        except Exception:
            return
        me = next((p for p in players if _names(p.get("riotId"), p.get("summonerName"), p.get("riotIdGameName")) & self.me), None)
        if not me:
            return
        self.players = _names(*[x for p in players for x in (p.get("riotId"), p.get("riotIdGameName"), p.get("summonerName"))])
        sc = me.get("scores") or {}
        if not self.match:
            started = self.clock() - game_time
            when = time.strftime("%Y-%m-%d %I.%M%p", time.localtime(started)).replace(" 0", " ").lower()
            raw_key = str(me.get("rawChampionName", "")).split("_")[-1]
            mode = mode_name(stats.get("gameMode"), stats.get("mapNumber"))
            champ = me.get("championName", "")
            self.match = {"id": f"lol-{int(started)}", "game": self.GAME, "mode": mode,
                          "raw_mode": stats.get("gameMode"), "champion": champ,
                          "champion_key": raw_key if raw_key and raw_key.isalnum() else "",
                          "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
                          "folder": f"{when[:10]} {when[11:]} {mode} - {champ}", "result": ""}
            log.info("Match: %s as %s (mode %s)", mode, champ, stats.get("gameMode"))
        self.match.update({"kills": sc.get("kills", 0), "deaths": sc.get("deaths", 0),
                           "assists": sc.get("assists", 0), "length": int(game_time)})
        self.on_match(dict(self.match))

    def _is_me(self, name):
        return bool(name) and bool(_names(name) & self.me)

    # ---------------------------------------------------------------- what counts
    def _event(self, e, cfg):
        on = events_config(cfg)
        t = self.offset + float(e.get("EventTime", 0)) if self.offset is not None else self.clock()
        name = e.get("EventName")
        hits = []   # (key, text, rank)
        mine_fight = False
        streak_start = t

        if name == "ChampionKill":
            killer = self._is_me(e.get("KillerName"))
            assist = any(self._is_me(a) for a in e.get("Assisters") or [])
            if killer or assist:
                mine_fight = True
                self.involved = [x for x in self.involved if t - x <= TEAMFIGHT_WINDOW] + [t]
                if len(self.involved) >= 3:
                    hits.append(("teamfight", "Teamfight", 3.5))
            if killer:
                self.my_kills = self.my_kills[-4:] + [t]
                hits.append(("every_kill", "Kill", 1))
            if self._is_me(e.get("VictimName")):
                hits.append(("death", "Death", 0.5))
                try:
                    self.on_death(self.GAME, t)
                except Exception:
                    log.exception("death review")
        elif name == "Multikill" and self._is_me(e.get("KillerName")):
            n = min(5, int(e.get("KillStreak", 2)))
            hits.append(MULTI.get(n, MULTI[2]))
            streak_start = self.my_kills[-n] if len(self.my_kills) >= n else t
        elif name == "FirstBlood" and self._is_me(e.get("Recipient")):
            hits.append(("first_blood", "First blood", 3))
        elif name == "Ace" and self._is_me(e.get("Acer")):
            hits.append(("ace", "Ace", 5.8))
        elif name in OBJECTIVES and self._is_me(e.get("KillerName")):
            what = OBJECTIVES[name]
            if name == "DragonKill" and str(e.get("DragonType", "")).lower() == "elder":
                what = "Elder Dragon"
            if str(e.get("Stolen")).lower() == "true":
                hits.append(("steal", f"{what} steal", 8))
            elif what in ("Baron", "Elder Dragon"):
                hits.append(("baron_elder", what, 5))
            elif name == "DragonKill":
                hits.append(("dragon", "Dragon", 2.5))
        elif name in ("TurretKilled", "InhibKilled") and self._is_me(e.get("KillerName")):
            hits.append(("structure", "Tower" if name == "TurretKilled" else "Inhibitor", 1.5 if name == "TurretKilled" else 2))
        elif name == "GameEnd":
            win = str(e.get("Result", "")).lower() == "win"
            if self.match:
                self.match["result"] = "Win" if win else "Loss"
                self.on_match(dict(self.match))
            hits.append(("victory", "Victory", 5.5) if win else ("defeat", "Defeat", 1))

        hits = [h for h in hits if on.get(h[0])] if cfg.get("auto_highlights", True) else []
        if hits:
            start = min(t, streak_start)
            if not self.play:
                self.play = {"labels": {}, "first": start, "last": t}
            self.play["first"] = min(self.play["first"], start)
            for key, text, rank in hits:
                group = "multi" if key in ("double", "triple", "quadra", "penta") else key
                if group not in self.play["labels"] or rank > self.play["labels"][group][0]:
                    self.play["labels"][group] = (rank, text)
            self.play["last"] = max(self.play["last"], t)
            log.info("Highlight moment: %s", ", ".join(h[1] for h in hits))
        elif mine_fight and self.play:
            self.play["last"] = max(self.play["last"], t)   # keep the clean-up in the same clip

    def label(self):
        items = sorted(self.play["labels"].values(), reverse=True)
        names = [txt for _, txt in items]
        if len(names) > 1:  # "Kill" and "Teamfight" are only worth naming on their own
            names = [n for n in names if n not in ("Kill", "Teamfight", "Death")] or names[:1]
        return " + ".join(names[:2])

    # ---------------------------------------------------------------- saving
    def _check_fire(self, cfg, force_after_game=False):
        if not self.play:
            return
        before = float(cfg.get("highlight_before", 5))
        after = float(cfg.get("highlight_after", 5))
        if self.clock() < self.play["last"] + after + SEGMENT_SLACK:
            return
        play, self.play = self.play, None
        cap = int(cfg.get("highlight_max_per_game", 10) or 0)
        label = self.label_for(play)
        if cap and self.saved >= cap:
            log.info("Skipped highlight %s, already saved %d this game", label, self.saved)
            return
        self.saved += 1
        try:
            self.save(label, play["first"] - before, play["last"] + after)
        except Exception:
            log.exception("Saving highlight failed")

    def label_for(self, play):
        keep, self.play = self.play, play
        try:
            return self.label()
        finally:
            self.play = keep
