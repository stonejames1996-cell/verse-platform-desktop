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

When it shows: lol_live.LeagueCompanion shows it while you're dead (shopping time), until you respawn,
and on a shortcut (Alt+Shift+I), together with your own numbers and your lane's item gold.
The pop-up is the same click-through window as the save pop-up. Unlike that one it does show up in
recordings, so a clip taken while it's open shows Verse Platform too.
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
        return self._image("item", item_id, px)

    def champ_icon(self, key, px):
        return self._image("champion", key, px)

    def _image(self, kind, name, px):
        folder = "icons" if kind == "item" else "champions"
        path = os.path.join(self.folder, self.version or "x", folder, f"{name}.png")
        try:
            if not os.path.exists(path):
                data = self._fetch(f"{DDRAGON}/cdn/{self.version}/img/{kind}/{name}.png", timeout=5)
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
    needs = []   # (score, need, why, champions to show)

    def faces(group, n=3):
        return [e["key"] for e in sorted(group, key=lambda e: -e["weight"])][:n]

    # magic or physical damage?
    total = sum(e["weight"] * e["damage"] for e in enemies)
    ap = sum(e["weight"] * e["damage"] * e["ap_share"] for e in enemies) / max(0.01, total)
    if ap >= 0.6:
        needs.append(((ap - 0.5) * 4, "magic", f"Most of their damage is magic ({round(ap * 100)}%)",
                      faces([e for e in enemies if e["ap_share"] >= 0.5])))
    elif ap <= 0.4:
        needs.append(((0.5 - ap) * 4, "physical", f"Most of their damage is physical ({round((1 - ap) * 100)}%)",
                      faces([e for e in enemies if e["ap_share"] < 0.5])))

    # healing
    healers = [e for e in enemies if e["key"] in HEALERS or _sum(gd, e["items"], "PercentLifeStealMod") > 0]
    heal = sum(e["weight"] for e in healers)
    if heal >= 1.8:
        needs.append((heal * 0.8, "heal", f"Lots of healing: {_names(healers)}", faces(healers)))

    # shields (Serpent's Fang is the answer, which is a physical damage item)
    shielders = [e for e in enemies if e["key"] in SHIELDERS or set(e["items"]) & SHIELD_ITEMS]
    shields = sum(e["weight"] for e in shielders)
    if shields >= 2:
        needs.append((shields * 0.6, "shields", f"Shields to break through: {_names(shielders)}", faces(shielders)))

    # a carry building crit or attack speed
    crit = [e for e in enemies if _sum(gd, e["items"], "FlatCritChanceMod") >= 0.4]
    if crit:
        top = max(crit, key=lambda e: e["weight"])
        needs.append((1.2 + top["weight"] * 0.4, "crit", f"{top['name']} is building crit", [top["key"]]))
    else:
        fast = [e for e in enemies if _sum(gd, e["items"], "PercentAttackSpeedMod") >= 0.6]
        if fast:
            top = max(fast, key=lambda e: e["weight"])
            needs.append((1.0 + top["weight"] * 0.3, "speed", f"{top['name']} attacks fast", [top["key"]]))

    # they're getting tanky
    tanks = [e for e in enemies if "Tank" in e["tags"][:1]]
    armor = _sum(gd, [i for e in enemies for i in e["items"]], "FlatArmorMod")
    mr = _sum(gd, [i for e in enemies for i in e["items"]], "FlatSpellBlockMod")
    hp = _sum(gd, [i for e in enemies for i in e["items"]], "FlatHPPoolMod")
    if armor >= 150 or (len(tanks) >= 2 and armor >= 60):
        needs.append((1.0 + armor / 200, "armor", f"They're stacking armour ({_names(tanks) or 'several of them'})", faces(tanks)))
    if mr >= 120 or (len(tanks) >= 2 and mr >= 50):
        needs.append((1.0 + mr / 160, "mr", f"They're stacking magic resist ({_names(tanks) or 'several of them'})", faces(tanks)))
    if hp >= 2500:
        big = [e for e in enemies if _sum(gd, e["items"], "FlatHPPoolMod") >= 800]
        needs.append((0.9 + hp / 4000, "hp", f"Big health bars: {_names(big)}", faces(big)))

    # lots of crowd control
    cc = [e for e in enemies if e["key"] in CC_HEAVY or e["name"] in CC_HEAVY]
    if len(cc) >= 3:
        needs.append((len(cc) * 0.45, "cc", f"Lots of crowd control: {_names(cc)}", faces(cc)))

    # a fed assassin
    fed = [e for e in enemies if "Assassin" in e["tags"] and e["kills"] - e["deaths"] >= 4]
    if fed:
        top = max(fed, key=lambda e: e["kills"] - e["deaths"])
        kind = "burst_ap" if top["ap_share"] >= 0.55 else "burst_ad"
        needs.append((1.5 + (top["kills"] - top["deaths"]) * 0.15, kind,
                      f"{top['name']} is fed ({top['kills']}/{top['deaths']})", [top["key"]]))

    owned = set(me["items"])
    has_boots = any(i in owned for i in BOOTS) or any(
        "Boots" in ((gd.items.get(i) or {}).get("tags") or []) and i != 1001 for i in owned)
    rows, used = [], set()
    for score, need, why, champs in sorted(needs, key=lambda n: -n[0]):
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
        rows.append({"why": why, "items": picks, "champs": champs})
        if len(rows) >= limit:
            break
    return {"style": style, "champion": me["name"], "rows": rows} if rows else None


# ---------------------------------------------------------------- the pop-up picture
def render(gd, result, scale=1.0, extras=None):
    """Glass card in the same style as the save pop-up: title, then each idea with item icons.
    extras (from lol_live): {"stats": [tiles], "gold": {...}} drawn above the ideas, under small labels."""
    extras = extras or {}
    result = result or {"rows": []}
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
    w = max(int(320 * s), pad * 2 + int(10 * s) + 3 * cell)
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
    face, face_gap = int(22 * s), int(4 * s)

    def faces_w(row):
        n = len(row.get("champs") or [])
        return n * face + max(0, n - 1) * face_gap + (int(8 * s) if n else 0)

    def why_h(row, lines):
        return max(len(lines) * lh(f_why), face if row.get("champs") else 0)

    f_sec = _font("Inter-SemiBold.otf", int(8.5 * s))
    f_big = _font("InterDisplay-Bold.otf", int(17 * s))
    f_small = _font("Inter-SemiBold.otf", int(9 * s))
    sec_h = lh(f_sec) + int(6 * s)
    tiles = extras.get("stats") or []
    gold = extras.get("gold")
    tile_h = lh(f_big) + lh(f_small) * 2 + int(10 * s)
    if tiles:
        h += sec_h + tile_h + int(12 * s)
    if gold:
        h += sec_h + face + int(14 * s)
    if result["rows"]:
        h += sec_h
    for row in result["rows"]:
        why = wrap(row["why"], f_why, w - pad * 2 - int(10 * s) - faces_w(row))
        names = [wrap(gd.name(i), f_item, cell - int(6 * s))[:2] for i in row["items"]]
        name_h = max((len(n) for n in names), default=1) * lh(f_item)
        bh = why_h(row, why) + int(6 * s) + icon + int(4 * s) + name_h + int(12 * s)
        blocks.append((row, why, names, bh))
        h += bh
    foot = ("Ideas from what's on the Tab screen. Your call." if result["rows"]
            else "Your numbers vs your own past games.")
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
    title, accent = ("Your game", "so far") if (tiles or gold) else ("Item ideas", "vs their team")
    d.text((tx, y + lh(f_label)), title, font=f_title, fill=WHITE)
    d.text((tx + probe.textlength(title + " ", font=f_title), y + lh(f_label)), accent, font=f_title, fill=SIGNAL)
    y += max(logo_px, lh(f_label) + lh(f_title)) + int(12 * s)
    UP, DOWN = (52, 211, 153, 255), (251, 191, 36, 255)   # green-ish up, amber down (differ in lightness too)

    def section(label):
        nonlocal y
        d.line([(x0, y - int(6 * s)), (w - pad, y - int(6 * s))], fill=(255, 255, 255, 22), width=max(1, int(s)))
        _spaced(d, (x0, y), label, f_sec, HAZE, 1.6 * s)
        y += sec_h

    def face_at(key, fx, fy):
        im = gd.champ_icon(key, face) if key else None
        if im is not None:
            m = Image.new("L", (face * 4, face * 4), 0)
            ImageDraw.Draw(m).ellipse((0, 0, face * 4 - 1, face * 4 - 1), fill=255)
            card.paste(im, (fx, fy), m.resize((face, face), Image.LANCZOS))
        d.ellipse((fx, fy, fx + face - 1, fy + face - 1), outline=(255, 255, 255, 70), width=max(1, int(s)))

    if tiles:
        section("YOUR GAME")
        tw = (w - pad - x0 - int(8 * s) * (len(tiles) - 1)) // max(1, len(tiles))
        for n, t in enumerate(tiles):
            cx = x0 + n * (tw + int(8 * s))
            d.rounded_rectangle((cx, y, cx + tw, y + tile_h), radius=int(8 * s), fill=(255, 255, 255, 12),
                                outline=(255, 255, 255, 26), width=max(1, int(s)))
            ix, iy = cx + int(8 * s), y + int(5 * s)
            d.text((ix, iy), t["value"], font=f_big, fill=WHITE)
            d.text((ix, iy + lh(f_big)), t["label"], font=f_small, fill=HAZE)
            if t.get("vs"):
                col = UP if t.get("up") else DOWN if t.get("up") is False else HAZE
                d.text((ix, iy + lh(f_big) + lh(f_small)), t["vs"], font=f_small, fill=col)
        y += tile_h + int(12 * s)
    if gold:
        section("ITEMS VS YOUR LANE")
        face_at(gold.get("me_key"), x0, y)
        face_at(gold.get("them_key"), x0 + face + face_gap, y)
        gx = x0 + face * 2 + face_gap + int(8 * s)
        diff = gold["me"] - gold["them"]
        line = f"{gold['me']:,} vs {gold['them']:,} gold"
        ty = y + (face - lh(f_why)) // 2
        d.text((gx, ty), line, font=f_why, fill=WHITE)
        tag = "even" if abs(diff) < 150 else f"{abs(diff):,} {'ahead' if diff > 0 else 'behind'}"
        d.text((gx + probe.textlength(line + "  ", font=f_why), ty), tag, font=f_why,
               fill=HAZE if abs(diff) < 150 else UP if diff > 0 else DOWN)
        y += face + int(14 * s)
    if result["rows"]:
        section("ITEM IDEAS VS THEIR TEAM")

    for bi, (row, why, names, bh) in enumerate(blocks):
        if bi:
            d.line([(x0, y - int(6 * s)), (w - pad, y - int(6 * s))], fill=(255, 255, 255, 22), width=max(1, int(s)))
        top_y, wh = y, why_h(row, why)
        for n, key in enumerate(row.get("champs") or []):   # their champion pictures, round
            fx = x0 + n * (face + face_gap)
            im = gd.champ_icon(key, face)
            if im is not None:
                m = Image.new("L", (face * 4, face * 4), 0)
                ImageDraw.Draw(m).ellipse((0, 0, face * 4 - 1, face * 4 - 1), fill=255)
                card.paste(im, (fx, top_y + (wh - face) // 2), m.resize((face, face), Image.LANCZOS))
            d.ellipse((fx, top_y + (wh - face) // 2, fx + face - 1, top_y + (wh - face) // 2 + face - 1),
                      outline=(255, 255, 255, 70), width=max(1, int(s)))
        ty = top_y + (wh - len(why) * lh(f_why)) // 2
        for line in why:
            d.text((x0 + faces_w(row), ty), line, font=f_why, fill=WHITE)
            ty += lh(f_why)
        y = top_y + wh + int(6 * s)
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
        y += bh - wh - int(6 * s)
    d.text((x0, y - int(2 * s)), foot, font=f_foot, fill=(120, 124, 136, 255))

    m = int(12 * s)
    full = Image.new("RGBA", (w + m * 2, h + m * 2), (0, 0, 0, 0))
    sh = Image.new("L", full.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((m, m + int(3 * s), m + w, m + h + int(3 * s)), radius=r, fill=130)
    full.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(int(7 * s))))
    full.alpha_composite(card, (m, m))
    return full.resize((max(1, full.width // 2), max(1, full.height // 2)), Image.LANCZOS)
