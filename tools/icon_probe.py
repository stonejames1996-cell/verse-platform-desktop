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
