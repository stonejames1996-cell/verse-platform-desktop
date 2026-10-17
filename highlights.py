"""
Auto highlights: saves a clip by itself when you make a play.

League of Legends: uses Riot's official Live Client Data API, which the game itself serves on
https://127.0.0.1:2999 during a match. It's read only, made by Riot for tools like this, and
doesn't touch the game, so it's safe with Vanguard. The app reads the match's event feed
(kills, multikills, aces, objective steals) once a second and clips the ones you made.

A fight often has several events in a row (kill, then double, then triple), so the app waits
until 6 seconds pass with no new play from you, then saves one clip named after the best moment.
That wait also catches the moment after the play.
"""

import json
import logging
import ssl
import threading
import time
import urllib.request

log = logging.getLogger("verse.highlights")

LOL_API = "https://127.0.0.1:2999/liveclientdata"
SETTLE_SECONDS = 6
MULTI = {2: "Double kill", 3: "Triple kill", 4: "Quadra kill", 5: "Pentakill"}
OBJECTIVES = {"BaronKill": "Baron", "DragonKill": "Dragon", "HeraldKill": "Herald", "HordeKill": "Voidgrubs",
              "AtakhanKill": "Atakhan"}

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


class LeagueHighlights:
    """Watches the League match and calls save(label) after a highlight."""

    GAME = "League of Legends"

    def __init__(self, get_cfg, is_playing, save):
        self.get_cfg, self.is_playing, self.save = get_cfg, is_playing, save
        self._reset()

    def _reset(self):
        self.me = set()
        self.last_id = None
        self.pending = None   # (rank, label)
        self.deadline = 0.0

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="highlights").start()

    def _loop(self):
        while True:
            try:
                cfg = self.get_cfg()
                if cfg.get("auto_highlights", True) and self.is_playing(self.GAME):
                    self._tick(cfg)
                else:
                    if self.pending:
                        self._fire()
                    self._reset()
            except Exception:
                log.debug("highlight poll", exc_info=True)
            time.sleep(1)

    def _tick(self, cfg):
        if not self.me:
            try:
                me = _get("/activeplayername")
                players = _get("/playerlist")
            except Exception:
                return  # still loading, or watching a replay or spectating
            mine = [p for p in players if _names(p.get("riotId"), p.get("summonerName")) & _names(me)]
            self.me = _names(me, *[x for p in mine for x in (p.get("riotId"), p.get("riotIdGameName"), p.get("summonerName"))])
            log.info("Watching League highlights for %s", me)
        try:
            events = _get("/eventdata").get("Events", [])
        except Exception:
            events = []
        if self.last_id is None:
            # first look at this match: skip anything that happened before we started watching
            self.last_id = max((e.get("EventID", -1) for e in events), default=-1)
        for e in events:
            if e.get("EventID", -1) > self.last_id:
                self.last_id = e["EventID"]
                self._event(e, cfg)
        if self.pending and time.time() >= self.deadline:
            self._fire()

    def _is_me(self, name):
        return bool(name) and bool(_names(name) & self.me)

    def _event(self, e, cfg):
        every_kill = cfg.get("highlight_level", "big") == "all"
        name = e.get("EventName")
        hit = None
        if name == "Multikill" and self._is_me(e.get("KillerName")):
            n = int(e.get("KillStreak", 2))
            hit = (n, MULTI.get(n, "Pentakill" if n > 5 else "Multi kill"))
        elif name == "Ace" and self._is_me(e.get("Acer")):
            hit = (3, "Ace")
        elif name in OBJECTIVES and self._is_me(e.get("KillerName")) and str(e.get("Stolen")).lower() == "true":
            hit = (4, f"{OBJECTIVES[name]} steal")
        elif name == "ChampionKill" and self._is_me(e.get("KillerName")):
            if every_kill:
                hit = (1, "Kill")
            elif self.pending:  # part of a fight we're already clipping: keep waiting for it to finish
                self.deadline = time.time() + SETTLE_SECONDS
        elif name == "FirstBlood" and self._is_me(e.get("Recipient")) and every_kill:
            hit = (1.5, "First blood")
        if hit:
            if not self.pending or hit[0] >= self.pending[0]:
                self.pending = hit
            self.deadline = time.time() + SETTLE_SECONDS
            log.info("Highlight: %s", hit[1])

    def _fire(self):
        label = self.pending[1]
        self.pending = None
        try:
            self.save(label)
        except Exception:
            log.exception("Saving highlight failed")
