"""One-off: find Riot's objective icons on CommunityDragon and fetch game logos (run on the build machine,
results go to the ci-checks branch so they can be copied into the app)."""
import json
import os
import urllib.request

OUT = os.path.abspath(os.path.join("checks_out", "icons"))
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "VersePlatformBuild"}


def get(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


found = {}
for d in ("plugins/rcp-fe-lol-match-history/global/default/", "game/assets/ux/minimap/icons/",
          "plugins/rcp-fe-lol-postgame/global/default/", "game/assets/ux/announcements/",
          "game/assets/ux/tft/", "plugins/rcp-be-lol-game-data/global/default/assets/"):
    try:
        items = json.loads(get("https://raw.communitydragon.org/json/latest/" + d))
        names = [i["name"] for i in items if any(k in i["name"].lower() for k in
                 ("dragon", "baron", "inhib", "elder", "herald", "horde", "grub", "atakhan", "tower", "turret"))]
        found[d] = names[:200]
    except Exception as e:
        found[d] = f"error {e}"
with open(os.path.join(OUT, "cdragon.json"), "w") as f:
    json.dump(found, f, indent=1)
print("cdragon:", {k: (len(v) if isinstance(v, list) else v) for k, v in found.items()})

GAMES = {
    "league-of-legends": "leagueoflegends.com", "valorant": "playvalorant.com", "counter-strike-2": "counter-strike.net",
    "fortnite": "fortnite.com", "apex-legends": "ea.com", "overwatch-2": "overwatch.blizzard.com",
    "rocket-league": "rocketleague.com", "dota-2": "dota2.com", "gta-v": "rockstargames.com",
    "rainbow-six-siege": "ubisoft.com", "call-of-duty": "callofduty.com", "marvel-rivals": "marvelrivals.com",
    "roblox": "roblox.com", "minecraft": "minecraft.net", "old-school-runescape": "oldschool.runescape.com",
    "elden-ring": "eldenring.bn-ent.net", "pubg": "pubg.com", "dead-by-daylight": "deadbydaylight.com",
    "escape-from-tarkov": "escapefromtarkov.com", "destiny-2": "bungie.net", "rust": "rust.facepunch.com",
    "world-of-warcraft": "worldofwarcraft.blizzard.com",
}
os.makedirs(os.path.join(OUT, "games"), exist_ok=True)
for slug, domain in GAMES.items():
    try:
        data = get(f"https://www.google.com/s2/favicons?domain={domain}&sz=64")
        with open(os.path.join(OUT, "games", slug + ".png"), "wb") as f:
            f.write(data)
        print("logo", slug, len(data))
    except Exception as e:
        print("logo", slug, "failed", e)


# second look: other addresses for the logos that came out wrong, and Riot's objective icons for the timers
ALT = {"apex-legends": ["playapex.com", "www.ea.com/games/apex-legends"], "call-of-duty": ["www.callofduty.com", "callofduty.com/warzone"],
       "dota-2": ["www.dota2.com", "dota2.com/home"], "elden-ring": ["en.bandainamcoent.eu/elden-ring", "www.bandainamcoent.com"],
       "rainbow-six-siege": ["rainbow6.com", "www.ubisoft.com/en-us/game/rainbow-six/siege-x"],
       "overwatch-2": ["playoverwatch.com", "overwatch.com"], "world-of-warcraft": ["worldofwarcraft.com", "www.worldofwarcraft.com"]}
for slug, doms in ALT.items():
    for i, dom in enumerate(doms):
        try:
            data = get(f"https://www.google.com/s2/favicons?domain={dom}&sz=64")
            with open(os.path.join(OUT, "games", f"{slug}__alt{i}.png"), "wb") as f:
                f.write(data)
        except Exception as e:
            print("alt", slug, dom, e)
os.makedirs(os.path.join(OUT, "lol"), exist_ok=True)
for name in ("baron", "dragon", "dragon_chemtech", "dragon_cloud", "dragon_elder", "dragon_hextech", "dragon_infernal",
             "dragon_mountain", "dragon_ocean", "inhibitor", "grub", "riftherald", "atakhan_v", "atakhan_r"):
    try:
        data = get(f"https://raw.communitydragon.org/latest/game/assets/ux/minimap/icons/{name}.png")
        with open(os.path.join(OUT, "lol", name + ".png"), "wb") as f:
            f.write(data)
        print("lol icon", name, len(data))
    except Exception as e:
        print("lol icon", name, "failed", e)
