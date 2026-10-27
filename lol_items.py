"""
League of Legends item ideas: a small pop-up with counter item ideas based on what the enemy team has.

Where the info comes from:
  * Riot's Live Client Data API (https://127.0.0.1:2999), the same local feed auto highlights use. It lists
    every player's champion and items, which is exactly what the Tab scoreboard shows, so nothing here is
    hidden information.
  * Data Dragon (Riot's public game data) for item names, stats and icons, so it stays right each patch.
    Items Riot removes simply stop being suggested.

Keeping inside Riot's rules (developer policy, League section):
  * it never says "buy this", it offers 2 or 3 choices per idea with the reason, and the player decides
  * no win rates, nothing from outside the game client, nothing a player couldn't see on Tab
  * not in Arena or TFT

When it shows: while you're dead (shopping time), until you respawn, and on a shortcut (Alt+Shift+I).
The pop-up is the same click-through window as the save pop-up, hidden from recordings.
"""

import json
import logging
import os
import threading
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFilter

import highlights

log = logging.getLogger("verse.items")

DDRAGON = "https://ddragon.leagueoflegends.com"
SKIP_MODES = {"CHERRY", "TFT", "STRAWBERRY", "TUTORIAL"}   # Arena, TFT, Swarm, tutorial

# champions whose kit leans on these things (kept short: the big, obvious ones)
HEALERS = {"Aatrox", "Soraka", "Vladimir", "Sylas", "DrMundo", "Warwick", "Yuumi", "Sona", "Nami", "Fiddlesticks",
           "Swain", "Briar", "Olaf", "Illaoi", "Volibear", "Trundle", "Maokai", "Kayn", "Nasus", "Renekton",
           "Zac", "Gwen", "Seraphine", "Milio", "Senna", "Samira", "Yorick", "Belveth", "Viego", "Darius", "Irelia"}
SHIELDERS = {"Lulu", "Janna", "Karma", "Sett", "Yone", "Seraphine", "Milio", "Renata", "Ivern", "Rakan", "Orianna",
             "Lux", "Taric", "Shen", "Skarner", "Rumble", "Mordekaiser", "Riven", "Camille", "Sion", "Galio",
             "Diana", "Kindred", "Ezreal"}
CC_HEAVY = {"Leona", "Morgana", "Lissandra", "Sejuani", "Amumu", "Malphite", "Nautilus", "Thresh", "Ashe", "Annie",
            "Veigar", "Zyra", "Rell", "Alistar", "Vi", "Skarner", "Blitzcrank", "Pyke", "Neeko", "Rammus", "Maokai",
            "Ornn", "Zac", "Warwick", "Fiddlesticks", "Swain", "Lux", "Xerath", "Taric", "Braum", "Poppy", "Jax",
            "Galio", "Wukong", "Kennen", "Sona", "Nami", "Bard", "Ahri", "Twisted Fate", "TwistedFate", "Mordekaiser"}
SHIELD_ITEMS = {3053, 6673, 6692, 3190, 6617, 3040, 3042, 4005, 2065}   # Sterak's, Shieldbow, Eclipse, Locket...

# counter item ideas for each need, by how you play: ad (physical damage), ap (magic), tank, support.
# Item numbers are Riot's; anything not in this patch's shop is skipped automatically.
OPTIONS = {
    "heal":     {"ad": [3033, 3123, 6609], "ap": [3165, 3916], "tank": [3075, 3076], "support": [3916, 3165]},
    "shields":  {"ad": [6695]},
    "magic":    {"tank": [4401, 2504, 3065, 6664, 3111], "ad": [3156, 3091, 3111], "ap": [3102, 3111],
                 "support": [3190, 3111]},
    "physical": {"tank": [3075, 3110, 3742, 3047], "ad": [3026, 6333, 3047], "ap": [3157, 3047],
                 "support": [3109, 3047]},
    "crit":     {"tank": [3143, 3110], "ad": [3026, 6333], "ap": [3157], "support": [3143, 3109]},
    "speed":    {"tank": [3110, 3143, 3047], "ad": [3047, 6333], "ap": [3157, 3047], "support": [3110, 3047]},
    "armor":    {"ad": [3036, 6694, 3071]},
    "mr":       {"ap": [3135, 3137]},
    "hp":       {"ad": [3153, 3036, 3071], "ap": [6653, 3135]},
    "cc":       {"ad": [3139, 3111], "ap": [3111, 3102], "tank": [3111], "support": [3222, 3111]},
    "burst_ap": {"ap": [3157, 3102], "ad": [3156, 3814], "support": [3190, 3109]},
    "burst_ad": {"ap": [3157], "ad": [3026, 6333, 3814], "support": [3109, 3190]},
}
BOOTS = {3111, 3047}


# ---------------------------------------------------------------- Riot's public game data
class GameData:
    """Item and champion info from Data Dragon, cached in the app's data folder per patch."""

    def __init__(self, folder):
        self.folder = os.path.join(folder, "lol_data")
        self.version = None
        self.items = {}      # id -> item json
        self.champs = {}     # id ("Kaisa") -> champion json
        self.lock = threading.Lock()
        self.checked = 0.0

    def _fetch(self, url, timeout=8):
        req = urllib.request.Request(url, headers={"User-Agent": "VersePlatform"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def _json(self, name, url):
        path = os.path.join(self.folder, self.version, name)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        data = json.loads(self._fetch(url))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(path + ".tmp", path)
        return data

    def ensure(self):
        """Loads the current patch's data (downloads it the first time). True when ready."""
        with self.lock:
            if self.items and time.time() - self.checked < 6 * 3600:
                return True
            try:
                version = json.loads(self._fetch(DDRAGON + "/api/versions.json"))[0]
            except Exception:
                version = self.version or self._newest_cached()
                if not version:
                    log.info("Couldn't reach Riot's game data for item ideas yet")
                    return bool(self.items)
            if version != self.version or not self.items:
                try:
                    self.version = version
                    base = f"{DDRAGON}/cdn/{version}/data/en_US"
                    self.items = {int(k): v for k, v in self._json("item.json", base + "/item.json")["data"].items()}
                    self.champs = self._json("champion.json", base + "/champion.json")["data"]
                    log.info("Item ideas ready (patch data %s)", version)
                except Exception:
                    log.warning("Couldn't load item data for %s", version, exc_info=True)
                    return bool(self.items)
            self.checked = time.time()
            return True

    def _newest_cached(self):
        try:
            names = [n for n in os.listdir(self.folder) if os.path.exists(os.path.join(self.folder, n, "item.json"))]
            return sorted(names, key=lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")])[-1]
        except (OSError, IndexError):
            return None

    def icon(self, item_id, px):
        path = os.path.join(self.folder, self.version or "x", "icons", f"{item_id}.png")
        try:
            if not os.path.exists(path):
                data = self._fetch(f"{DDRAGON}/cdn/{self.version}/img/item/{item_id}.png", timeout=5)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
            im = Image.open(path).convert("RGBA")
            return im.resize((px, px), Image.LANCZOS)
        except Exception:
            return None

    def in_shop(self, item_id, map_id):
        it = self.items.get(item_id)
        if not it:
            return False
        if not (it.get("gold") or {}).get("purchasable", True):
            return False
        maps = it.get("maps") or {}
        return maps.get(str(map_id), True) if map_id else True

    def stats(self, item_id):
        return (self.items.get(item_id) or {}).get("stats") or {}

    def gold(self, item_id):
        return ((self.items.get(item_id) or {}).get("gold") or {}).get("total", 0)

    def name(self, item_id):
        return (self.items.get(item_id) or {}).get("name", "")

    def champ(self, raw_name, display=""):
        """Live data gives "game_character_displayname_Kaisa"; Data Dragon calls it "Kaisa"."""
        key = str(raw_name or "").rsplit("_", 1)[-1]
        if key in self.champs:
            return key, self.champs[key]
        for k, c in self.champs.items():
            if c.get("name") == display:
                return k, c
        return key or display, {}


# ---------------------------------------------------------------- working out the ideas
def _sum(gd, items, stat):
    return sum(gd.stats(i).get(stat, 0) for i in items)


def _player(gd, p):
    key, champ = gd.champ(p.get("rawChampionName"), p.get("championName"))
    items = [int(i.get("itemID", 0)) for i in (p.get("items") or []) if i.get("itemID")]
    sc = p.get("scores") or {}
    info = champ.get("info") or {}
    base_ap = (info.get("magic", 5) / max(1, info.get("magic", 5) + info.get("attack", 5)))
    ap, ad = _sum(gd, items, "FlatMagicDamageMod"), _sum(gd, items, "FlatPhysicalDamageMod")
    item_ap = ap / (ap + ad * 1.5) if ap + ad > 20 else base_ap
    gold = sum(gd.gold(i) for i in items)
    tags = champ.get("tags") or []
    return {
        "key": key, "name": p.get("championName") or champ.get("name") or key, "items": items, "tags": tags,
        "ap_share": (base_ap + item_ap) / 2, "gold": gold,
        "kills": sc.get("kills", 0), "deaths": sc.get("deaths", 0),
        # how much of a threat they are right now: items and kills
        "weight": max(0.5, 1 + gold / 3000 + sc.get("kills", 0) * 0.15 - sc.get("deaths", 0) * 0.05),
        "damage": 0.6 if tags[:1] == ["Tank"] else 1.0,
    }


def my_style(me):
    """How I play this game: ad, ap, tank or support."""
    tags = me["tags"]
    first = tags[0] if tags else ""
    if first == "Tank" or (first == "Fighter" and "Tank" in tags and me["ap_share"] < 0.5):
        return "tank"
    if first == "Support" and me["gold"] < 6000:
        return "support"
    return "ap" if me["ap_share"] >= 0.55 else "ad"


def _names(players, limit=3):
    names = [p["name"] for p in sorted(players, key=lambda p: -p["weight"])][:limit]
    return ", ".join(names)


def ideas(gd, game, limit=3):
    """game: the allgamedata JSON. Returns {"style", "rows": [{"why", "items": [ids]}]} or None."""
    data = game.get("gameData") or {}
    if str(data.get("gameMode", "")).upper() in SKIP_MODES:
        return None
    map_id = data.get("mapNumber")
    active = game.get("activePlayer") or {}
    mine = highlights._names(active.get("riotId"), active.get("summonerName"))
    players = game.get("allPlayers") or []
    me_raw = next((p for p in players if highlights._names(p.get("riotId"), p.get("summonerName"),
                                                           p.get("riotIdGameName")) & mine), None)
    if not me_raw:
        return None
    me = _player(gd, me_raw)
    enemies = [_player(gd, p) for p in players if p.get("team") != me_raw.get("team")]
    if not enemies:
        return None
    style = my_style(me)
    needs = []   # (score, need, why)

    # magic or physical damage?
    total = sum(e["weight"] * e["damage"] for e in enemies)
    ap = sum(e["weight"] * e["damage"] * e["ap_share"] for e in enemies) / max(0.01, total)
    if ap >= 0.6:
        needs.append(((ap - 0.5) * 4, "magic", f"Most of their damage is magic ({round(ap * 100)}%)"))
    elif ap <= 0.4:
        needs.append(((0.5 - ap) * 4, "physical", f"Most of their damage is physical ({round((1 - ap) * 100)}%)"))

    # healing
    healers = [e for e in enemies if e["key"] in HEALERS or _sum(gd, e["items"], "PercentLifeStealMod") > 0]
    heal = sum(e["weight"] for e in healers)
    if heal >= 1.8:
        needs.append((heal * 0.8, "heal", f"Lots of healing: {_names(healers)}"))

    # shields (Serpent's Fang is the answer, which is a physical damage item)
    shielders = [e for e in enemies if e["key"] in SHIELDERS or set(e["items"]) & SHIELD_ITEMS]
    shields = sum(e["weight"] for e in shielders)
    if shields >= 2:
        needs.append((shields * 0.6, "shields", f"Shields to break through: {_names(shielders)}"))

    # a carry building crit or attack speed
    crit = [e for e in enemies if _sum(gd, e["items"], "FlatCritChanceMod") >= 0.4]
    if crit:
        top = max(crit, key=lambda e: e["weight"])
        needs.append((1.2 + top["weight"] * 0.4, "crit", f"{top['name']} is building crit"))
    else:
        fast = [e for e in enemies if _sum(gd, e["items"], "PercentAttackSpeedMod") >= 0.6]
        if fast:
            top = max(fast, key=lambda e: e["weight"])
            needs.append((1.0 + top["weight"] * 0.3, "speed", f"{top['name']} attacks fast"))

    # they're getting tanky
    tanks = [e for e in enemies if "Tank" in e["tags"][:1]]
    armor = _sum(gd, [i for e in enemies for i in e["items"]], "FlatArmorMod")
    mr = _sum(gd, [i for e in enemies for i in e["items"]], "FlatSpellBlockMod")
    hp = _sum(gd, [i for e in enemies for i in e["items"]], "FlatHPPoolMod")
    if armor >= 150 or (len(tanks) >= 2 and armor >= 60):
        needs.append((1.0 + armor / 200, "armor", f"They're stacking armour ({_names(tanks) or 'several of them'})"))
    if mr >= 120 or (len(tanks) >= 2 and mr >= 50):
        needs.append((1.0 + mr / 160, "mr", f"They're stacking magic resist ({_names(tanks) or 'several of them'})"))
    if hp >= 2500:
        big = [e for e in enemies if _sum(gd, e["items"], "FlatHPPoolMod") >= 800]
        needs.append((0.9 + hp / 4000, "hp", f"Big health bars: {_names(big)}"))

    # lots of crowd control
    cc = [e for e in enemies if e["key"] in CC_HEAVY or e["name"] in CC_HEAVY]
    if len(cc) >= 3:
        needs.append((len(cc) * 0.45, "cc", f"Lots of crowd control: {_names(cc)}"))

    # a fed assassin
    fed = [e for e in enemies if "Assassin" in e["tags"] and e["kills"] - e["deaths"] >= 4]
    if fed:
        top = max(fed, key=lambda e: e["kills"] - e["deaths"])
        kind = "burst_ap" if top["ap_share"] >= 0.55 else "burst_ad"
        needs.append((1.5 + (top["kills"] - top["deaths"]) * 0.15, kind,
                      f"{top['name']} is fed ({top['kills']}/{top['deaths']})"))

    owned = set(me["items"])
    has_boots = any(i in owned for i in BOOTS) or any(
        "Boots" in ((gd.items.get(i) or {}).get("tags") or []) and i != 1001 for i in owned)
    rows, used = [], set()
    for score, need, why in sorted(needs, key=lambda n: -n[0]):
        picks = []
        for item in OPTIONS.get(need, {}).get(style, []):
            if item in owned or item in used or not gd.in_shop(item, map_id):
                continue
            if item in BOOTS and has_boots:
                continue
            picks.append(item)
        picks = picks[:3]
        if len(picks) < 2:
            continue   # always a real choice (Riot: highlight decisions, don't make them)
        used.update(picks)
        rows.append({"why": why, "items": picks})
        if len(rows) >= limit:
            break
    return {"style": style, "champion": me["name"], "rows": rows} if rows else None


# ---------------------------------------------------------------- the pop-up picture
def render(gd, result, scale=1.0):
    """Glass card in the same style as the save pop-up: title, then each idea with item icons."""
    from overlay import HAZE, SIGNAL, WHITE, _logo
    from watermark import _font, _spaced
    s = scale * 2
    pad, icon, gap = int(16 * s), int(34 * s), int(10 * s)
    f_label = _font("Inter-SemiBold.otf", int(9.5 * s))
    f_title = _font("InterDisplay-Bold.otf", int(16 * s))
    f_why = _font("Inter-SemiBold.otf", int(11.5 * s))
    f_item = _font("Inter-SemiBold.otf", int(9.5 * s))
    f_foot = _font("Inter-SemiBold.otf", int(9 * s))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    cell = int(86 * s)
    w = max(int(300 * s), pad * 2 + int(10 * s) + 3 * cell)
    logo_px = int(26 * s)

    def wrap(text, font, width):
        words, lines, line = text.split(), [], ""
        for wd in words:
            t = (line + " " + wd).strip()
            if probe.textlength(t, font=font) <= width or not line:
                line = t
            else:
                lines.append(line)
                line = wd
        return lines + ([line] if line else [])

    def lh(font):
        a, d = font.getmetrics()
        return a + d

    # measure
    h = pad + max(logo_px, lh(f_label) + lh(f_title)) + int(12 * s)
    blocks = []
    for row in result["rows"]:
        why = wrap(row["why"], f_why, w - pad * 2 - int(10 * s))
        names = [wrap(gd.name(i), f_item, cell - int(6 * s))[:2] for i in row["items"]]
        name_h = max((len(n) for n in names), default=1) * lh(f_item)
        bh = len(why) * lh(f_why) + int(6 * s) + icon + int(4 * s) + name_h + int(12 * s)
        blocks.append((row, why, names, bh))
        h += bh
    foot = "Ideas from what's on the Tab screen. Your call."
    h += lh(f_foot) + pad
    r = int(14 * s)

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
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, outline=(255, 255, 255, 34), width=max(1, int(s)))
    d.line([(r, int(s)), (w - r, int(s))], fill=(255, 255, 255, 46), width=max(1, int(s)))
    d.rounded_rectangle((int(5 * s), r, int(8 * s), h - r), radius=int(2 * s), fill=SIGNAL)

    # header: logo, "VERSE PLATFORM" label, "Item ideas" title
    x0, y = pad + int(4 * s), pad
    lg = _logo(logo_px)
    if lg:
        card.alpha_composite(lg, (x0, y + (lh(f_label) + lh(f_title) - lg.height) // 2))
    tx = x0 + logo_px + int(10 * s)
    _spaced(d, (tx, y), "VERSE PLATFORM", f_label, HAZE, 2.0 * s)
    d.text((tx, y + lh(f_label)), "Item ideas", font=f_title, fill=WHITE)
    d.text((tx + probe.textlength("Item ideas ", font=f_title), y + lh(f_label)),
           f"vs their team", font=f_title, fill=SIGNAL)
    y += max(logo_px, lh(f_label) + lh(f_title)) + int(12 * s)

    for row, why, names, bh in blocks:
        d.line([(x0, y - int(6 * s)), (w - pad, y - int(6 * s))], fill=(255, 255, 255, 22), width=max(1, int(s)))
        for line in why:
            d.text((x0, y), line, font=f_why, fill=WHITE)
            y += lh(f_why)
        y += int(6 * s)
        for n, (item, name) in enumerate(zip(row["items"], names)):
            cx = x0 + n * cell
            im = gd.icon(item, icon)
            if im is not None:
                m = Image.new("L", (icon, icon), 0)
                ImageDraw.Draw(m).rounded_rectangle((0, 0, icon - 1, icon - 1), radius=int(6 * s), fill=255)
                card.paste(im, (cx, y), m)
            d.rounded_rectangle((cx, y, cx + icon - 1, y + icon - 1), radius=int(6 * s),
                                outline=(255, 255, 255, 50), width=max(1, int(s)))
            ny = y + icon + int(4 * s)
            for line in name:
                d.text((cx, ny), line, font=f_item, fill=HAZE)
                ny += lh(f_item)
        y += bh - len(why) * lh(f_why) - int(6 * s)
    d.text((x0, y - int(2 * s)), foot, font=f_foot, fill=(120, 124, 136, 255))

    m = int(12 * s)
    full = Image.new("RGBA", (w + m * 2, h + m * 2), (0, 0, 0, 0))
    sh = Image.new("L", full.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((m, m + int(3 * s), m + w, m + h + int(3 * s)), radius=r, fill=130)
    full.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(int(7 * s))))
    full.alpha_composite(card, (m, m))
    return full.resize((max(1, full.width // 2), max(1, full.height // 2)), Image.LANCZOS)


# ---------------------------------------------------------------- watching the match
class ItemIdeas:
    """Shows the item ideas pop-up while you're dead, and on the shortcut."""

    GAME = "League of Legends"

    def __init__(self, get_cfg, is_playing, overlay, data_dir, get=None):
        self.get_cfg, self.is_playing, self.overlay = get_cfg, is_playing, overlay
        self.gd = GameData(data_dir)
        self.get = get or highlights._get
        self.dead = False
        self.asked = 0.0

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="item-ideas").start()

    def on(self):
        return bool(self.get_cfg().get("lol_item_ideas", True))

    def show_now(self, *_):
        """The shortcut: show the ideas for a few seconds."""
        self.asked = time.time()

    def _loop(self):
        while True:
            try:
                if self.on() and self.is_playing(self.GAME):
                    self._tick()
                else:
                    self.dead = False
            except Exception:
                log.debug("item ideas poll", exc_info=True)
            time.sleep(0.5)

    def _tick(self):
        asked = self.asked and time.time() - self.asked < 2
        try:
            game = self.get("/allgamedata")
        except Exception:
            return   # loading screen, or not in a match
        me = self._me(game)
        dead = bool(me and me.get("isDead"))
        if dead and not self.dead:
            self.dead = True
            wait = float(me.get("respawnTimer") or 0)
            if wait >= 4:   # not worth it for a very short death timer
                self._show(game, seconds=min(wait, 75), until=self._still_dead)
        elif not dead:
            self.dead = False
        if asked:
            self.asked = 0
            self._show(game, seconds=12, until=None, say_nothing=False)

    def _me(self, game):
        active = game.get("activePlayer") or {}
        mine = highlights._names(active.get("riotId"), active.get("summonerName"))
        return next((p for p in game.get("allPlayers") or []
                     if highlights._names(p.get("riotId"), p.get("summonerName"), p.get("riotIdGameName")) & mine), None)

    def _still_dead(self):
        try:
            me = self._me(self.get("/allgamedata"))
            return bool(me and me.get("isDead"))
        except Exception:
            return False

    def _show(self, game, seconds, until, say_nothing=True):
        if not self.gd.ensure():
            if not say_nothing:
                self.overlay.show("Item ideas need Riot's game data", accent="", sub="Couldn't download it, check your internet", ok=False)
            return
        res = ideas(self.gd, game)
        if not res:
            if not say_nothing:
                self.overlay.show("No item ideas right now", accent="", sub="Nothing on their team stands out yet")
            return
        scale = self.overlay.scale() if hasattr(self.overlay, "scale") else 1.0
        img = render(self.gd, res, scale)
        log.info("Item ideas shown: %s", " | ".join(r["why"] for r in res["rows"]))
        self.overlay.show_image(img, seconds=seconds, until=until, place="left")
