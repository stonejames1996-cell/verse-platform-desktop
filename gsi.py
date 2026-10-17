"""
Auto highlights for Counter-Strike 2 and Dota 2.

Both games have Valve's official Game State Integration: drop a small cfg file in the game's
folder and the game sends its live state (your kills, deaths, round, score...) to a web address
on this PC while you play. It's read only and made by Valve for tools like this, so it's VAC safe.
The app writes those cfg files itself and listens on 127.0.0.1 only.

Dota 2 also needs "-gamestateintegration" in its Steam launch options (Valve's rule).
"""

import datetime
import glob
import json
import logging
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from highlights import events_config

log = logging.getLogger("verse.gsi")
IS_WINDOWS = sys.platform == "win32"
SLACK = 2.5            # the recorder writes 2 second chunks, wait for the last one to finish
CFG_NAME = "gamestate_integration_verse.cfg"

CS2 = "Counter-Strike 2"
DOTA = "Dota 2"


# ------------------------------------------------------------------------- installing the cfg files

def steam_libraries():
    """Every Steam library folder on this PC."""
    roots = []
    if IS_WINDOWS:
        import winreg
        for hive, key, val in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                               (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                               (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(os.path.normpath(winreg.QueryValueEx(k, val)[0]))
            except OSError:
                pass
        roots.append(r"C:\Program Files (x86)\Steam")
    else:
        roots.append(os.path.expanduser("~/.steam/steam"))
    libs = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        libs.append(root)
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                for p in re.findall(r'"path"\s+"([^"]+)"', f.read()):
                    libs.append(os.path.normpath(p.replace("\\\\", "\\")))
        except OSError:
            pass
    seen, out = set(), []
    for l in libs:
        if os.path.normcase(l) not in seen:
            seen.add(os.path.normcase(l))
            out.append(l)
    return out


def _cfg_text(uri, token, data):
    rows = "\n".join(f'    "{k}" "1"' for k in data)
    return (f'"Verse Platform"\n{{\n  "uri" "{uri}"\n  "timeout" "1.0"\n  "buffer" "0.1"\n  "throttle" "0.1"\n'
            f'  "heartbeat" "5.0"\n  "auth"\n  {{\n    "token" "{token}"\n  }}\n  "data"\n  {{\n{rows}\n  }}\n}}\n')


def install_cfgs(port, token):
    """Writes (or refreshes) the cfg file for every copy of CS2 and Dota 2 found. Returns {game: [paths]}."""
    done = {CS2: [], DOTA: []}
    for lib in steam_libraries():
        common = os.path.join(lib, "steamapps", "common")
        targets = (
            (CS2, os.path.join(common, "Counter-Strike Global Offensive", "game", "csgo", "cfg"),
             _cfg_text(f"http://127.0.0.1:{port}/cs2", token,
                       ["provider", "map", "round", "player_id", "player_state", "player_match_stats"])),
            (DOTA, os.path.join(common, "dota 2 beta", "game", "dota", "cfg", "gamestate_integration"),
             _cfg_text(f"http://127.0.0.1:{port}/dota2", token, ["provider", "map", "player", "hero", "events"])),
        )
        for game, folder, text in targets:
            if not os.path.isdir(os.path.dirname(folder)):
                continue
            try:
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, CFG_NAME)
                old = ""
                if os.path.exists(path):
                    with open(path, encoding="utf-8", errors="replace") as f:
                        old = f.read()
                if old != text:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(text)
                    log.info("%s live game info set up: %s", game, path)
                done[game].append(path)
            except OSError as e:
                log.warning("Couldn't set up %s live game info in %s: %s", game, folder, e)
    return done


# ------------------------------------------------------------------------- the local web address

class GSIServer:
    """Receives the games' updates on 127.0.0.1 and hands them to the right tracker."""

    def __init__(self, port, token, handlers):
        self.port, self.token, self.handlers = port, token, handlers
        self.httpd = None

    def start(self):
        srv = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(min(n, 2_000_000)) or b"{}")
                except Exception:
                    body = None
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                if not isinstance(body, dict) or (body.get("auth") or {}).get("token") != srv.token:
                    return
                h = srv.handlers.get(self.path.strip("/").split("?")[0])
                if h:
                    try:
                        h.update(body)
                    except Exception:
                        log.debug("game update", exc_info=True)

            def log_message(self, *a):
                pass

        for port in (self.port, self.port + 1, self.port + 2, 0):
            try:
                self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
                break
            except OSError:
                continue
        if not self.httpd:
            log.warning("Couldn't open the local port for CS2 and Dota 2 highlights")
            return None
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="gsi").start()
        return self.port


# ------------------------------------------------------------------------- shared highlight logic

def _when(t):
    return time.strftime("%Y-%m-%d %I.%M%p", time.localtime(t)).replace(" 0", " ").lower()


class GameTracker:
    """Collects the moments of one play, then saves it as one clip once it's over."""

    GAME = ""
    CHAIN = 0          # extra seconds to wait for the next kill of a multi kill

    def __init__(self, get_cfg, is_playing, save, on_match=None, on_death=None, clock=time.time):
        self.get_cfg, self.is_playing, self.save, self.clock = get_cfg, is_playing, save, clock
        self.on_match = on_match or (lambda m: None)
        self.on_death = on_death or (lambda game, t: None)
        self.lock = threading.RLock()
        self.play = None
        self.saved = 0
        self.match = None
        self.last_update = 0.0
        threading.Thread(target=self._loop, daemon=True, name=f"hl-{self.GAME}").start()

    # called by subclasses
    def hit(self, key, text, rank, t, start=None, hold=0.0):
        cfg = self.get_cfg()
        if not cfg.get("auto_highlights", True) or not events_config(cfg).get(key):
            return False
        with self.lock:
            start = min(t, start if start is not None else t)
            if not self.play:
                self.play = {"labels": {}, "first": start, "last": t, "hold": 0.0}
            p = self.play
            p["first"] = min(p["first"], start)
            p["last"] = max(p["last"], t)
            p["hold"] = max(p["hold"], hold)
            group = "multi" if key in ("double", "triple", "quadra", "penta") else key
            if group not in p["labels"] or rank > p["labels"][group][0]:
                p["labels"][group] = (rank, text)
        log.info("%s highlight moment: %s", self.GAME, text)
        return True

    def death(self, t):
        try:
            self.on_death(self.GAME, t)
        except Exception:
            log.exception("death review")

    def set_match(self, **fields):
        if not self.match:
            return
        changed = any(self.match.get(k) != v for k, v in fields.items())
        self.match.update(fields)
        if changed:
            self.on_match(dict(self.match))

    def new_match(self, mid, mode, what, joiner, icon_url="", key=""):
        started = self.clock()
        when = _when(started)
        self.match = {"id": mid, "game": self.GAME, "mode": mode, "champion": what, "champion_key": key,
                      "joiner": joiner, "icon_url": icon_url,
                      "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
                      "folder": f"{when[:10]} {when[11:]} {mode} - {what}", "result": ""}
        self.saved = 0
        log.info("Match: %s %s %s", mode, joiner.strip(), what)
        self.on_match(dict(self.match))

    def label(self, play):
        items = sorted(play["labels"].values(), reverse=True)
        names = [txt for _, txt in items]
        if len(names) > 1:
            names = [n for n in names if n not in ("Kill", "Teamfight", "Death")] or names[:1]
        return " + ".join(names[:2])

    def _loop(self):
        while True:
            time.sleep(1)
            try:
                self.fire()
            except Exception:
                log.debug("highlight check", exc_info=True)

    def fire(self, force=False):
        cfg = self.get_cfg()
        after = float(cfg.get("highlight_after", 5))
        before = float(cfg.get("highlight_before", 5))
        with self.lock:
            p = self.play
            if not p:
                return
            ready_at = max(p["last"] + after + SLACK, p["last"] + self.CHAIN, p["hold"])
            if self.clock() < ready_at and not force:
                return
            self.play = None
        cap = int(cfg.get("highlight_max_per_game", 10) or 0)
        label = self.label(p)
        if cap and self.saved >= cap:
            log.info("Skipped highlight %s, already saved %d this game", label, self.saved)
            return
        self.saved += 1
        self.save(label, p["first"] - before, p["last"] + after)

    def update(self, data):
        self.last_update = self.clock()
        if self.is_playing(self.GAME):
            self.handle(data, self.clock())

    def handle(self, data, now):
        raise NotImplementedError


# ------------------------------------------------------------------------- Counter-Strike 2

CS_MODES = {"competitive": "Competitive", "premier": "Premier", "casual": "Casual", "deathmatch": "Deathmatch",
            "scrimcomp2v2": "Wingman", "gungameprogressive": "Arms Race", "survival": "Danger Zone",
            "custom": "Custom", "training": "Practice"}
CS_MULTI = {2: ("double", "2K", 4), 3: ("triple", "3K", 6), 4: ("quadra", "4K", 9), 5: ("penta", "Ace", 10)}


def cs_map_name(raw):
    name = re.sub(r"^(de|cs|ar|dz|gd|aim|fy)_", "", str(raw or "")).replace("_", " ").strip()
    return name.title() or "Unknown map"


class CS2Highlights(GameTracker):
    """Kills are counted per round: a 3K across a round is one clip from the first kill to the last."""

    GAME = CS2

    def __init__(self, *a, **k):
        self.reset()
        super().__init__(*a, **k)

    def reset(self):
        self.round_kills = []      # wall times of my kills this round
        self.last_rk = 0
        self.alive = False
        self.last_health = 0
        self.team = ""
        self.phase = ""
        self.map_phase = ""
        self.ended = False
        self.map_key = None

    def _close_round(self, now, hold=0.0):
        kills = self.round_kills
        self.round_kills = []
        n = len(kills)
        if n >= 2:
            key, text, rank = CS_MULTI[min(n, 5)]
            self.hit(key, text, rank, kills[-1], start=kills[0], hold=hold)
        elif n == 1:
            self.hit("every_kill", "Kill", 1, kills[0], hold=hold)

    def handle(self, d, now):
        prov, pl, mp, rnd = d.get("provider") or {}, d.get("player") or {}, d.get("map") or {}, d.get("round") or {}
        me = str(prov.get("steamid") or "")
        if not mp:
            if self.match:   # back in the menus
                self.fire(force=True)
                self.match = None
                self.reset()
            return
        key = (mp.get("name"), mp.get("mode"))
        if key != self.map_key and mp.get("phase") in ("warmup", "live"):
            self.map_key = key
            self.reset()
            self.map_key = key
            mode = CS_MODES.get(str(mp.get("mode") or "").lower(), str(mp.get("mode") or "Match").title())
            self.new_match(f"cs2-{int(now)}", mode, cs_map_name(mp.get("name")), " on ")

        mine = str(pl.get("steamid") or "") == me and me
        st = pl.get("state") or {}
        if mine:
            self.team = pl.get("team") or self.team
            rk = int(st.get("round_kills") or 0)
            if rk < self.last_rk:          # new round started
                self.last_rk = 0
            for _ in range(rk - self.last_rk):
                self.round_kills.append(now)
            self.last_rk = rk
            hp = int(st.get("health") or 0)
            if self.alive and hp == 0 and rnd.get("phase") == "live":
                self._died(now)
            self.alive = hp > 0
            self.last_health = hp
            ms = pl.get("match_stats") or {}
            if self.match:
                self.set_match(kills=ms.get("kills", 0), deaths=ms.get("deaths", 0), assists=ms.get("assists", 0))
        elif self.alive and rnd.get("phase") == "live" and pl:
            # watching a team mate: you died
            self._died(now)
            self.alive = False

        phase = rnd.get("phase") or ""
        if phase == "over" and self.phase != "over":
            self._close_round(now)
        self.phase = phase

        if mp.get("phase") == "gameover" and not self.ended:
            self.ended = True
            self._close_round(now)
            ct = int((mp.get("team_ct") or {}).get("score") or 0)
            t = int((mp.get("team_t") or {}).get("score") or 0)
            if self.team:
                mine_s, theirs = (ct, t) if self.team == "CT" else (t, ct)
                win = mine_s > theirs
                if self.match:
                    self.set_match(result="Win" if win else ("Loss" if mine_s < theirs else "Draw"))
                if mine_s != theirs:
                    self.hit("victory", "Victory", 5.5, now) if win else self.hit("defeat", "Defeat", 1, now)

    def _died(self, now):
        self.hit("death", "Death", 0.5, now)
        self._close_round(now)       # whatever you got this round is done
        self.death(now)


# ------------------------------------------------------------------------- Dota 2

DOTA_MULTI = {2: ("double", "Double Kill", 4), 3: ("triple", "Triple Kill", 6),
              4: ("quadra", "Ultra Kill", 9), 5: ("penta", "Rampage", 10)}
DOTA_CHAIN = 18      # Dota's multi kill window, roughly


def dota_hero(raw):
    key = str(raw or "").replace("npc_dota_hero_", "")
    special = {"nevermore": "Shadow Fiend", "zuus": "Zeus", "furion": "Nature's Prophet", "wisp": "Io",
               "obsidian_destroyer": "Outworld Destroyer", "shredder": "Timbersaw", "skeleton_king": "Wraith King",
               "rattletrap": "Clockwerk", "magnataur": "Magnus", "windrunner": "Windranger", "life_stealer": "Lifestealer",
               "treant": "Treant Protector", "centaur": "Centaur Warrunner", "abyssal_underlord": "Underlord",
               "doom_bringer": "Doom", "queenofpain": "Queen of Pain", "antimage": "Anti-Mage",
               "vengefulspirit": "Vengeful Spirit", "necrolyte": "Necrophos", "spirit_breaker": "Spirit Breaker"}
    return key, special.get(key, key.replace("_", " ").title() or "Hero")


class DotaHighlights(GameTracker):
    GAME = DOTA
    CHAIN = 6     # wait a bit longer for a multi kill to continue

    def __init__(self, *a, **k):
        self.reset()
        super().__init__(*a, **k)

    def reset(self):
        self.kills = self.deaths = self.assists = None
        self.chain = []          # wall times of my kills in the current multi kill
        self.involved = []
        self.team = ""
        self.ended = False
        self.matchid = None

    def handle(self, d, now):
        mp, pl, hero = d.get("map") or {}, d.get("player") or {}, d.get("hero") or {}
        if "kills" not in pl:       # spectating, or in the menus
            if self.match and not mp:
                self.fire(force=True)
                self.match = None
                self.reset()
            return
        mid = str(mp.get("matchid") or "")
        if mid and mid != self.matchid:
            self.reset()
            self.matchid = mid
            key, name = dota_hero(hero.get("name"))
            icon = f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{key}.png" if key else ""
            self.new_match(f"dota-{mid}", "Dota", name, " as ", icon_url=icon)
        elif self.match and not self.match.get("champion_key") and hero.get("name") and self.match["champion"] == "Hero":
            key, name = dota_hero(hero.get("name"))
            self.set_match(champion=name, icon_url=f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{key}.png")
        self.team = pl.get("team_name") or self.team
        k, de, a = int(pl.get("kills") or 0), int(pl.get("deaths") or 0), int(pl.get("assists") or 0)
        if self.kills is None:
            self.kills, self.deaths, self.assists = k, de, a
            return
        for _ in range(max(0, k - self.kills)):
            # like Dota itself: each kill has to come within the window of the one before
            self.chain = (self.chain if self.chain and now - self.chain[-1] <= DOTA_CHAIN else []) + [now]
            self.involved = [x for x in self.involved if now - x <= 10] + [now]
            n = len(self.chain)
            if n >= 2:
                key, text, rank = DOTA_MULTI[min(n, 5)]
                self.hit(key, text, rank, now, start=self.chain[0])
            else:
                total = int(mp.get("radiant_score") or 0) + int(mp.get("dire_score") or 0)
                if self.kills == 0 and total <= 1:
                    self.hit("first_blood", "First blood", 3, now)
                self.hit("every_kill", "Kill", 1, now)
            if len(self.involved) >= 3:
                self.hit("teamfight", "Teamfight", 3.5, now, start=self.involved[0])
        for _ in range(max(0, a - self.assists)):
            self.involved = [x for x in self.involved if now - x <= 10] + [now]
            if len(self.involved) >= 3:
                self.hit("teamfight", "Teamfight", 3.5, now, start=self.involved[0])
        if de > self.deaths:
            self.chain = []
            self.hit("death", "Death", 0.5, now)
            self.death(now)
        self.kills, self.deaths, self.assists = k, de, a
        if self.match:
            self.set_match(kills=k, deaths=de, assists=a)
        win = str(mp.get("win_team") or "none").lower()
        if win not in ("", "none") and not self.ended:
            self.ended = True
            won = win == str(self.team).lower()
            if self.match:
                self.set_match(result="Win" if won else "Loss")
            self.hit("victory", "Victory", 5.5, now) if won else self.hit("defeat", "Defeat", 1, now)
