"""
OP.GG data for the League match analysis: your rank, how players at your rank do on your champion, and
how the top players on that champion farm. Uses OP.GG's public MCP server (https://mcp-api.op.gg/mcp),
the same one Verse's website uses for its League and TFT guides.

  * profile(riot_id, region): your Solo/Duo rank (tier, division, LP, wins, losses)
  * champion_at_tier(champion, position, tier): KDA, win rate and games for that champion at that rank
  * top_players(champion, region): CS, gold and KDA per minute averaged over the champion's leaderboard
  * recent_game(riot_id, region, started, champion): your real end of game numbers once OP.GG has the
    match (gold earned, damage to champions, the lobby's average rank)

Everything is cached on disk (a day for champion stats, an hour for your rank) and every call is allowed
to fail: the analysis just leaves that part out. Riot's rules allow aggregate stats and your own stats.

OP.GG answers in a compact text form, for example:
    class AverageStats: play,win_rate,kda
    LolGetChampionAnalysis(Data(Summary(AverageStats(102819,0.51,2.17))))
parse() turns that into dicts using the "class" lines for the field names.
"""

import json
import logging
import os
import re
import threading
import time
import urllib.request

log = logging.getLogger("verse.opgg")

URL = "https://mcp-api.op.gg/mcp"

# League's own server codes -> OP.GG's region names
REGIONS = {"OC1": "OCE", "NA1": "NA", "EUW1": "EUW", "EUN1": "EUNE", "KR": "KR", "BR1": "BR", "LA1": "LAN",
           "LA2": "LAS", "JP1": "JP", "TR1": "TR", "RU": "RU", "PH2": "PH", "SG2": "SG", "TH2": "TH", "TW2": "TW",
           "VN2": "VN", "ME1": "ME"}
POSITIONS = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "mid", "BOTTOM": "adc", "UTILITY": "support"}
MEDAL = "https://opgg-static.akamaized.net/images/medals_new/{}.png"   # OP.GG's rank icons, e.g. platinum.png
TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]


# ---------------------------------------------------------------- OP.GG's text format
def parse(text):
    """Turns OP.GG's "Name(value,...)" answer into dicts and lists."""
    fields = {}
    body_lines = []
    for line in text.splitlines():
        m = re.match(r"\s*class\s+(\w+)\s*:\s*(.*)$", line)
        if m:
            fields[m.group(1)] = [f.strip() for f in m.group(2).split(",") if f.strip()]
        elif line.strip():
            body_lines.append(line)
    s = "\n".join(body_lines).strip()
    pos = 0

    def ws():
        nonlocal pos
        while pos < len(s) and s[pos] in " \n\r\t":
            pos += 1

    def value():
        nonlocal pos
        ws()
        c = s[pos]
        if c == '"':
            end = pos + 1
            while s[end] != '"':
                end += 2 if s[end] == "\\" else 1
            raw = s[pos:end + 1]
            pos = end + 1
            return json.loads(raw)
        if c == "[":
            pos += 1
            out = []
            ws()
            if s[pos] == "]":
                pos += 1
                return out
            while True:
                out.append(value())
                ws()
                if s[pos] == ",":
                    pos += 1
                    continue
                pos += 1   # ]
                return out
        m = re.compile(r"[A-Za-z_]\w*").match(s, pos)
        if m:
            name = m.group(0)
            pos = m.end()
            if name in ("null", "None"):
                return None
            if name in ("true", "True"):
                return True
            if name in ("false", "False"):
                return False
            ws()
            if pos < len(s) and s[pos] == "(":
                pos += 1
                args = []
                ws()
                if s[pos] != ")":
                    while True:
                        args.append(value())
                        ws()
                        if s[pos] == ",":
                            pos += 1
                            continue
                        break
                pos += 1   # )
                names = fields.get(name) or []
                if len(names) == 1 and len(args) == 1:
                    return {names[0]: args[0]}
                return {names[i] if i < len(names) else f"_{i}": v for i, v in enumerate(args)}
            return name
        m = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?").match(s, pos)
        if m:
            pos = m.end()
            return float(m.group(0)) if (m.group(1) or m.group(2)) else int(m.group(0))
        raise ValueError(f"can't read OP.GG answer at {pos}: {s[pos:pos + 30]!r}")
    return value()


def champion_name(name):
    """ "Kai'Sa" -> "KAISA", "Miss Fortune" -> "MISS_FORTUNE", "Dr. Mundo" -> "DR_MUNDO"."""
    name = str(name or "").replace("'", "").replace(".", " ").replace("&", " ")
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")


def rank_text(tier, division=None):
    if not tier:
        return ""
    t = str(tier).title()
    return t if t.upper() in ("MASTER", "GRANDMASTER", "CHALLENGER") or not division else f"{t} {division}"


def league_region():
    """The server League is set to on this PC (from League's own settings file), as OP.GG names it."""
    paths = []
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            n = (p.info.get("name") or "").lower()
            if n in ("league of legends.exe", "leagueclient.exe", "leagueclientux.exe") and p.info.get("exe"):
                d = os.path.dirname(p.info["exe"])
                for up in (d, os.path.dirname(d)):
                    paths.append(os.path.join(up, "Config", "LeagueClientSettings.yaml"))
    except Exception:
        pass
    for drive in ("C:", "D:", "E:"):
        paths.append(os.path.join(drive + os.sep, "Riot Games", "League of Legends", "Config", "LeagueClientSettings.yaml"))
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                m = re.search(r'^\s*region:\s*"?([A-Za-z0-9]+)"?', f.read(), re.M)
            if m:
                code = m.group(1).upper()
                return REGIONS.get(code, REGIONS.get(code + "1", code))
        except OSError:
            continue
    return ""


# ---------------------------------------------------------------- the client
class OPGG:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "opgg_cache.json")
        self.lock = threading.Lock()
        self.session = None
        self.rid = 0
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.cache = json.load(f)
        except (OSError, ValueError):
            self.cache = {}

    def _post(self, method, params):
        self.rid += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self.rid, "method": method, "params": params}).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "User-Agent": "VersePlatformDesktop"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(URL, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.headers.get("Mcp-Session-Id"):
                self.session = r.headers["Mcp-Session-Id"]
            text = r.read().decode("utf-8", "replace")
        if not text.lstrip().startswith("{"):
            text = next((ln[5:] for ln in text.splitlines() if ln.startswith("data:")), "{}")
        return json.loads(text or "{}")

    def call(self, tool, args, ttl):
        """One OP.GG tool call, cached for ttl seconds. Returns the parsed answer or None."""
        key = tool + json.dumps(args, sort_keys=True)
        with self.lock:
            hit = self.cache.get(key)
            if hit and time.time() - hit["at"] < ttl:
                return hit["v"]
            try:
                if not self.session:
                    self._post("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                              "clientInfo": {"name": "verse-platform-desktop", "version": "1"}})
                r = self._post("tools/call", {"name": tool, "arguments": args})
                if r.get("error"):
                    self.session = None
                    log.info("OP.GG %s: %s", tool, r["error"].get("message"))
                    return None
                content = (r.get("result") or {}).get("content") or []
                text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
                if (r.get("result") or {}).get("isError") or not text:
                    log.info("OP.GG %s had no answer: %s", tool, text[:200])
                    return None
                v = parse(text)
            except Exception as e:
                self.session = None
                log.info("OP.GG %s failed: %s", tool, e)
                return None
            self.cache[key] = {"at": time.time(), "v": v}
            if len(self.cache) > 300:   # keep the newest
                for k in sorted(self.cache, key=lambda k: self.cache[k]["at"])[:100]:
                    del self.cache[k]
            try:
                with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(self.cache, f)
                os.replace(self.path + ".tmp", self.path)
            except OSError:
                pass
            return v

    # ------------------------------------------------------------ the bits the app uses
    def profile(self, riot_id, region):
        name, _, tag = str(riot_id or "").partition("#")
        if not (name and tag and region):
            return None
        v = self.call("lol_get_summoner_profile", {
            "game_name": name, "tag_line": tag, "region": region, "lang": "en_US",
            "desired_output_fields": ["data.summoner.league_stats[].tier_info.{division,lp,tier,tier_image_url}",
                                      "data.summoner.league_stats[].{game_type,lose,win}"]}, 3600)
        try:
            stats = v["data"]["summoner"]["league_stats"]
        except (TypeError, KeyError):
            return None
        solo = next((x for x in stats if x.get("game_type") == "SOLORANKED"), None)
        info = (solo or {}).get("tier_info") or {}
        if not info.get("tier"):
            return None
        return {"tier": info["tier"], "division": info.get("division"), "lp": info.get("lp"),
                "wins": solo.get("win"), "losses": solo.get("lose"), "image": info.get("tier_image_url") or "",
                "text": rank_text(info["tier"], info.get("division"))}

    def champion_at_tier(self, champion, position, tier):
        pos = POSITIONS.get(str(position or "").upper())
        if not (champion and pos):
            return None
        args = {"champion": champion_name(champion), "position": pos, "game_mode": "ranked", "lang": "en_US",
                "desired_output_fields": ["data.summary.average_stats.{kda,play,win_rate}",
                                          "data.summary.positions[].stats.{kda,play,win_rate}",
                                          "data.summary.positions[].name"]}
        if tier:
            args["tier"] = str(tier).lower()
        v = self.call("lol_get_champion_analysis", args, 86400)
        try:
            summ = v["data"]["summary"]
        except (TypeError, KeyError):
            return None
        row = next((p.get("stats") for p in summ.get("positions") or [] if str(p.get("name", "")).lower()
                    in (pos, {"adc": "adc"}.get(pos, pos))), None) or summ.get("average_stats") or {}
        if not row.get("kda"):
            return None
        return {"kda": row["kda"], "win_rate": row.get("win_rate"), "games": row.get("play"),
                "tier": rank_text(tier) if tier else "all ranks"}

    def top_players(self, champion, region):
        if not (champion and region):
            return None
        v = self.call("lol_list_champion_leaderboard", {
            "champion": champion_name(champion), "region": region,
            "desired_output_fields": ["leaderboard[].most_champion_stat.{assist,death,game_length_second,gold_earned,"
                                      "kill,minion_kill,neutral_minion_kill,play,damage_dealt_to_champions}"]}, 86400)
        rows = [r.get("most_champion_stat") or {} for r in (v or {}).get("leaderboard") or []]
        rows = [r for r in rows if r.get("game_length_second")]
        if not rows:
            return None
        secs = sum(r["game_length_second"] for r in rows)
        tot = lambda k: sum(r.get(k) or 0 for r in rows)
        mins = secs / 60
        return {"cs_min": (tot("minion_kill") + tot("neutral_minion_kill")) / mins, "gpm": tot("gold_earned") / mins,
                "kda": (tot("kill") + tot("assist")) / max(1, tot("death")), "dpm": tot("damage_dealt_to_champions") / mins,
                "players": len(rows), "games": tot("play")}

    def recent_game(self, riot_id, region, started_ts, champion):
        """Your numbers from OP.GG for the game that started around started_ts (needs OP.GG to have it)."""
        name, _, tag = str(riot_id or "").partition("#")
        if not (name and tag and region):
            return None
        args = {"game_name": name, "tag_line": tag, "region": region, "lang": "en_US", "limit": 5,
                "desired_output_fields": [
                    "data.game_history[].{created_at,game_length_second,game_type,id}",
                    "data.game_history[].average_tier_info.{division,tier}",
                    "data.game_history[].participants[].{champion_name,position,team_key}",
                    "data.game_history[].participants[].summoner.{game_name,tagline}",
                    "data.game_history[].participants[].stats.{assist,death,gold_earned,kill,minion_kill,"
                    "neutral_minion_kill,op_score,total_damage_dealt_to_champions,ward_place,vision_wards_bought_in_game}"]}
        v = self.call("lol_list_summoner_matches", args, 120)
        games = ((v or {}).get("data") or {}).get("game_history") or []
        from datetime import datetime
        for g in games:
            try:
                at = datetime.fromisoformat(str(g.get("created_at"))).timestamp()
            except ValueError:
                continue
            if abs(at - started_ts) > 15 * 60:
                continue
            parts = g.get("participants") or []
            me = next((p for p in parts if str((p.get("summoner") or {}).get("game_name", "")).lower() == name.lower()), None)
            if not me and len(parts) == 1:
                me = parts[0]
            if not me or (champion and champion_name(me.get("champion_name")) != champion_name(champion)):
                continue
            st = me.get("stats") or {}
            mins = max(1, (g.get("game_length_second") or 0) / 60)
            avg = g.get("average_tier_info") or {}
            return {"gold": st.get("gold_earned"), "gpm": round((st.get("gold_earned") or 0) / mins, 1),
                    "damage": st.get("total_damage_dealt_to_champions"),
                    "dpm": round((st.get("total_damage_dealt_to_champions") or 0) / mins, 1),
                    "op_score": st.get("op_score"), "lobby": rank_text(avg.get("tier"), avg.get("division")),
                    "lobby_image": MEDAL.format(str(avg["tier"]).lower()) if avg.get("tier") else "",
                    "game_id": g.get("id")}
        return None
