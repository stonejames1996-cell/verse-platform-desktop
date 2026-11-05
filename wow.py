"""World of Warcraft auto highlights (WoW: Forever, Classic and retail).

Blizzard's web API only knows about your character after you log out, and there's no live feed for
apps. But WoW has its own combat log: type /combatlog in chat and the game writes every fight to
    World of Warcraft\\_forever_\\Logs\\WoWCombatLog-<date>.txt
(older clients: WoWCombatLog.txt). It's Blizzard's own feature, the same file Warcraft Logs uses.
We only read that text file, nothing touches the game.

A line looks like (advanced logging adds more fields in the middle, we read around them):
    11/5/2026 14:03:12.345  SPELL_DAMAGE,Player-1-0A,"Me-Realm",0x511,0x0,Creature-0-...,"Mob",0xa48,0x0,133,"Fireball",0x4,...,812,0,4,0,0,0,1,nil,nil,nil

Moments we clip (each one can be switched off in Settings):
    boss_kill   Boss down: <name>                  ENCOUNTER_END with success
    boss_wipe   Wipe on <name>                     ENCOUNTER_END without success (off by default)
    every_kill  Killing blow                       you (or your pet) killed an enemy player
    double...   Double kill, Triple kill...        enemy players killed close together
    aoe         <n> mobs at once                   you (or your pet) killed 4+ mobs within a few seconds
    big_crit    Biggest hit: 1,234                 a crit bigger than any so far this session
    big_heal    Biggest heal: 1,234                same for heals
    death       Died to <name>                     your deaths (off by default, also feeds death review)
"""
import csv
import datetime
import glob
import logging
import os
import re
import threading
import time

from gsi import GameTracker

log = logging.getLogger("Verse Platform")

GAME = "World of Warcraft"      # the Settings key; covers WoW: Forever, Classic and retail
CHAIN = 10.0                    # seconds between enemy player kills for a double, triple...
AOE_WINDOW = 6.0                # mobs killed within this many seconds count as one pull
AOE_MIN = 4
BIG_MIN_SAMPLES = 20            # crits/heals seen before "biggest so far" starts to count
BIG_GAP = 180.0                 # at most one biggest hit (and one biggest heal) clip per 3 minutes
PER_HOUR = True                 # the per game highlight cap counts per hour, sessions can be long
MULTI = {2: ("double", "Double kill", 6), 3: ("triple", "Triple kill", 7),
         4: ("quadra", "Quadra kill", 9), 5: ("penta", "Pentakill", 10)}

# combat log unit flags
MINE = 0x1
HOSTILE = 0x40
TYPE_PLAYER = 0x400
TYPE_PET = 0x1000
TYPE_GUARDIAN = 0x2000

DAMAGE = {"SWING_DAMAGE", "SPELL_DAMAGE", "RANGE_DAMAGE", "SPELL_PERIODIC_DAMAGE"}
HEALS = {"SPELL_HEAL", "SPELL_PERIODIC_HEAL"}
WANTED = DAMAGE | HEALS | {"PARTY_KILL", "UNIT_DIED", "ENCOUNTER_START", "ENCOUNTER_END", "ZONE_CHANGE",
                           "COMBAT_LOG_VERSION"}


def is_wow(label):
    s = (label or "").strip().lower()
    return s == "world of warcraft" or s.startswith("wow")


# ------------------------------------------------------------------------- reading lines

_LINE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))? (\d{1,2}):(\d{2}):(\d{2})\.(\d+)([+-]\d{1,2})?\s+(.*)$")


def parse_time(m, now=None):
    """The time stamp at the start of a line -> this PC's clock (seconds). WoW writes local time.
    If it's far from now (odd clock, old file), now is used so clips still line up with the recording."""
    now = time.time() if now is None else now
    mon, day, year, hh, mm, ss, frac = m.group(1, 2, 3, 4, 5, 6, 7)
    try:
        y = int(year) if year else datetime.datetime.fromtimestamp(now).year
        if y < 100:
            y += 2000
        dt = datetime.datetime(y, int(mon), int(day), int(hh), int(mm), int(ss), int(frac[:6].ljust(6, "0")))
        t = dt.timestamp()
    except ValueError:
        return now
    return t if abs(t - now) < 300 else now


def split_fields(rest):
    """'SPELL_DAMAGE,Player-1,"Me-Realm",0x511,...' -> list of fields (quotes removed)."""
    try:
        return next(csv.reader([rest]))
    except (csv.Error, StopIteration):
        return rest.split(",")


def flags(v):
    try:
        return int(v, 16) if str(v).startswith("0x") else int(v)
    except (TypeError, ValueError):
        return 0


def num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _trim(f):
    """Retail adds a damage type ('ST' / 'AOE') at the very end; drop it so the end lines up."""
    while f and f[-1] in ("ST", "AOE"):
        f = f[:-1]
    return f


def damage_info(f, base=True):
    """(amount, crit) from a damage line, reading from the end. WoW: Forever (log version 22) writes
    ... amount, baseAmount, overkill, school, resisted, blocked, absorbed, critical, glancing, crushing
    e.g. a melee crit '9,4,-1,1,0,0,0,1,nil,nil' did 9 (4 before the crit). Some clients add isOffHand at
    the end, and very old ones have no baseAmount (base=False)."""
    f = _trim(f)
    if len(f) < 12:
        return 0, False
    tail = 0
    while tail < 4 and f[-1 - tail] in ("1", "nil"):
        tail += 1
    if tail < 3:
        return 0, False
    crit_i = len(f) - tail
    return num(f[crit_i - (7 if base else 6)]), f[crit_i] == "1"


def heal_info(f, base=True):
    """(amount actually healed, crit) from a heal line: ... amount, [baseAmount,] overhealing, absorbed, critical"""
    f = _trim(f)
    if len(f) < 12:
        return 0, False
    amount = num(f[-5] if base else f[-4])
    return max(0, amount - num(f[-3])), f[-1] == "1"


def is_me(flag):
    return bool(flag & MINE) and bool(flag & TYPE_PLAYER)


def is_mine(flag):
    """Me or my pet/guardian (a hunter's pet getting the killing blow still counts)."""
    return bool(flag & MINE) and bool(flag & (TYPE_PLAYER | TYPE_PET | TYPE_GUARDIAN))


def name_only(n):
    return (n or "").split("-")[0].strip() or "?"


def nice(n):
    return f"{n:,}"


# ------------------------------------------------------------------------- finding the log

def logs_dirs():
    """WoW's Logs folders: next to every running Wow*.exe first, then the usual install spots."""
    out = []
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            n = (p.info.get("name") or "").lower()
            if n.startswith("wow") and n.endswith(".exe") and p.info.get("exe"):
                d = os.path.join(os.path.dirname(p.info["exe"]), "Logs")
                if d not in out:
                    out.append(d)
    except Exception:
        log.debug("WoW: process list", exc_info=True)
    for base in (r"C:\Program Files (x86)\World of Warcraft", r"C:\Program Files\World of Warcraft"):
        for flavour in ("_forever_", "_retail_", "_classic_era_", "_classic_"):
            d = os.path.join(base, flavour, "Logs")
            if d not in out:
                out.append(d)
    return [d for d in out if os.path.isdir(d)]


def newest_log(dirs):
    best, best_t = None, 0.0
    for d in dirs:
        for p in glob.glob(os.path.join(d, "WoWCombatLog*.txt")):
            try:
                t = os.path.getmtime(p)
            except OSError:
                continue
            if t > best_t:
                best, best_t = p, t
    return best, best_t


# ------------------------------------------------------------------------- turning the log into highlights

class WowHighlights(GameTracker):
    GAME = GAME
    CHAIN = 4.0       # wait a little after the last moment, mobs in a pull die close together

    def __init__(self, *a, on_hint=None, find_dirs=logs_dirs, poll=1.0, **k):
        self.on_hint = on_hint or (lambda text: None)   # "type /combatlog" reminder
        self.find_dirs = find_dirs
        self.poll = poll
        self.reset()
        super().__init__(*a, **k)
        self._stop = threading.Event()
        self._active = False
        threading.Thread(target=self._tail_loop, daemon=True, name="wow-log").start()

    def reset(self):
        self.path = None
        self.pos = 0
        self.partial = ""
        self.started = time.time()
        self.hinted = False
        self.lines = 0
        self.base = True            # log version 20+ has baseAmount after amount
        self.encounters = {}        # encounter id -> start time
        self.pvp_kills = []         # times of enemy player kills in the current chain
        self.mob_kills = []         # times of mob kills in the current pull
        self.my_targets = {}        # unit id -> last time I (or my pet) damaged it
        self.counted = set()        # unit ids already counted as my kill
        self.crits = []
        self.heals = []
        self.best_crit = 0
        self.best_heal = 0
        self.last_big = {"big_crit": 0.0, "big_heal": 0.0}
        self.zone = ""
        self.hour_start = time.time()
        self.stats = {"boss_kills": 0, "wipes": 0, "pvp_kills": 0, "mobs": 0, "deaths": 0,
                      "best_crit": 0, "best_heal": 0}

    # --- session
    def new_session(self, label="World of Warcraft"):
        self.reset()
        self.started = self.clock()
        self._active = True
        when = time.strftime("%Y%m%d-%H%M%S")
        # folder names can't have a colon ("WoW: Forever" -> "WoW Forever")
        self.new_match(f"wow-{when}", re.sub(r'[\\/:*?"<>|]', "", label), "Session", " \u00b7 ", icon_url="")
        self.match["game"] = label        # clips are recorded under the name the app shows (WoW: Forever)
        self.on_match(dict(self.match))
        self.path, mtime = newest_log(self.find_dirs())
        if self.path:
            # only new lines count; a log written in the last few seconds is read from the start
            try:
                size = os.path.getsize(self.path)
            except OSError:
                size = 0
            self.pos = 0 if self.clock() - mtime < 5 and size < 200000 else size
            log.info("WoW highlights: reading %s", self.path)
        else:
            log.info("WoW highlights: no combat log yet (type /combatlog in WoW)")

    def end_session(self):
        self._active = False
        self.fire(force=True)
        s = dict(self.stats, minutes=round((self.clock() - self.started) / 60))
        log.info("WoW session: %s", s)
        return s if any(v for k, v in s.items() if k != "minutes") else None

    def handle(self, data, now):   # no live feed, see _tail_loop
        pass

    def label(self, play):
        items = sorted(play["labels"].values(), reverse=True)
        names = [txt for _, txt in items]
        if len(names) > 1:
            names = [n for n in names if n not in ("Killing blow", "Died")] or names[:1]
        return " + ".join(names[:2])

    def hit(self, key, text, rank, t, start=None, hold=0.0):
        # WoW writes its log in bursts, so moments can arrive together even when they happened far
        # apart. A moment well after the current one starts its own clip.
        gap = float(self.get_cfg().get("highlight_after", 5)) + self.CHAIN
        with self.lock:
            far = self.play and t - self.play["last"] > gap
        if far:
            self.fire(force=True)
        return super().hit(key, text, rank, t, start=start, hold=hold)

    def fire(self, force=False):
        if PER_HOUR and self.clock() - self.hour_start > 3600:
            self.hour_start = self.clock()
            self.saved = 0
        super().fire(force)

    # --- reading the file
    def _tail_loop(self):
        while not self._stop.is_set():
            time.sleep(self.poll)
            if not self._active:
                continue
            try:
                self.read_new()
            except Exception:
                log.debug("WoW combat log read", exc_info=True)

    def read_new(self):
        # /combatlog started after the game (or a new day's file): switch to the newest one
        path, mtime = newest_log(self.find_dirs())
        if path and path != self.path and mtime >= self.started - 5:
            log.info("WoW highlights: reading %s", path)
            self.path, self.pos, self.partial = path, 0, ""
        if not self.path:
            if not self.hinted and self.clock() - self.started > 90:
                self.hinted = True
                self.on_hint("Type /combatlog in WoW chat to turn on WoW highlights")
            return
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return
        if size < self.pos:      # file was replaced
            self.pos = 0
        if size == self.pos:
            if not self.hinted and self.lines == 0 and self.clock() - self.started > 90:
                self.hinted = True
                self.on_hint("Type /combatlog in WoW chat to turn on WoW highlights")
            return
        with open(self.path, "rb") as f:
            f.seek(self.pos)
            chunk = f.read(4 * 1024 * 1024)
            self.pos = f.tell()
        text = self.partial + chunk.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self.partial = lines.pop()       # last bit may be half a line
        self.feed(lines)

    def feed(self, lines, now=None):
        for line in lines:
            line = line.rstrip("\r")
            m = _LINE.match(line)
            if not m:
                continue
            rest = m.group(9)
            ev = rest.split(",", 1)[0]
            if ev not in WANTED:
                continue
            self.lines += 1
            t = parse_time(m, now if now is not None else self.clock())
            try:
                self.event(ev, split_fields(rest), t)
            except Exception:
                log.debug("WoW line skipped: %s", line[:160], exc_info=True)

    # --- the moments
    def event(self, ev, f, t):
        if ev == "COMBAT_LOG_VERSION" and len(f) >= 2:
            self.base = num(f[1]) >= 20
            log.info("WoW combat log version %s", f[1])
        elif ev == "ENCOUNTER_START" and len(f) >= 3:
            self.encounters[f[1]] = t
            log.info("WoW: pulled %s", f[2])
        elif ev == "ENCOUNTER_END" and len(f) >= 6:
            name, ok = f[2], f[5] == "1"
            began = self.encounters.pop(f[1], None)
            start = max(began, t - 30) if began else t - 15
            if ok:
                self.stats["boss_kills"] += 1
                log.info("WoW: boss down %s", name)
                self.hit("boss_kill", f"Boss down: {name}", 9, t, start=start)
            else:
                self.stats["wipes"] += 1
                self.hit("boss_wipe", f"Wipe on {name}", 2, t, start=start)
        elif ev == "ZONE_CHANGE" and len(f) >= 3:
            self.zone = f[2]
            self.set_match(zone=self.zone)
        elif ev == "PARTY_KILL" and len(f) >= 9:
            if not is_mine(flags(f[3])) or f[5] in self.counted:
                return
            self.counted.add(f[5])
            dest = flags(f[7])
            if dest & TYPE_PLAYER and dest & HOSTILE:
                self._pvp_kill(name_only(f[6]), t)
            else:
                self._mob_kill(t)
        elif ev == "UNIT_DIED" and len(f) >= 9:
            dest = flags(f[7])
            if is_me(dest):
                self.stats["deaths"] += 1
                self.hit("death", "Died", 1, t)
                self.death(t)
            elif f[5] not in self.counted and t - self.my_targets.get(f[5], -1e9) <= 6:
                # WoW: Forever logs most deaths without a killer (no PARTY_KILL), so a unit that dies
                # within a few seconds of my last hit on it counts as my kill
                self.counted.add(f[5])
                if dest & TYPE_PLAYER and dest & HOSTILE:
                    self._pvp_kill(name_only(f[6]), t)
                elif not dest & TYPE_PLAYER:
                    self._mob_kill(t)
        elif ev in DAMAGE and len(f) >= 9:
            if is_mine(flags(f[3])):
                self.my_targets[f[5]] = t
                if len(self.my_targets) > 500:
                    for k in sorted(self.my_targets, key=self.my_targets.get)[:250]:
                        del self.my_targets[k]
                amount, crit = damage_info(f, self.base)
                if crit and amount > 0:
                    self._big("big_crit", "Biggest hit", amount, t, self.crits)
        elif ev in HEALS and len(f) >= 9:
            if is_me(flags(f[3])):
                amount, crit = heal_info(f, self.base)
                if crit and amount > 0:
                    self._big("big_heal", "Biggest heal", amount, t, self.heals)

    def _pvp_kill(self, who, t):
        if self.pvp_kills and t - self.pvp_kills[-1] <= CHAIN:
            self.pvp_kills.append(t)
        else:
            self.pvp_kills = [t]
        n = len(self.pvp_kills)
        self.stats["pvp_kills"] += 1
        log.info("WoW: killing blow on a player (%d in a row)", n)
        self.hit("every_kill", "Killing blow", 3, t)
        if n >= 2:
            key, text, rank = MULTI[min(n, 5)]
            self.hit(key, text, rank, t, start=self.pvp_kills[0])

    def _mob_kill(self, t):
        if self.mob_kills and t - self.mob_kills[-1] <= AOE_WINDOW:
            self.mob_kills.append(t)
        else:
            self.mob_kills = [t]
        self.stats["mobs"] += 1
        n = len(self.mob_kills)
        if n >= AOE_MIN:
            # rank grows with the pull so "6 mobs at once" replaces "4 mobs at once" in the same clip
            self.hit("aoe", f"{n} mobs at once", 5 + min(n, 40) / 100, t, start=self.mob_kills[0])

    def _big(self, key, text, amount, t, seen):
        best_key = "best_crit" if key == "big_crit" else "best_heal"
        best = self.stats[best_key]
        seen.append(amount)
        if len(seen) > 400:
            del seen[:200]
        if amount <= best:
            return
        self.stats[best_key] = amount
        if len(seen) < BIG_MIN_SAMPLES or t - self.last_big[key] < BIG_GAP:
            return
        typical = sorted(seen)[len(seen) // 2]
        if amount < typical * 1.5:
            return
        self.last_big[key] = t
        log.info("WoW: %s %s", text.lower(), amount)
        self.hit(key, f"{text}: {nice(amount)}", 4, t)
