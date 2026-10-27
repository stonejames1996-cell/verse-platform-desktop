"""One-off look at what the OP.GG MCP server returns (run on the build machine, results go to ci-checks).
Read only: lists the tools and calls a few League ones with sample inputs."""
import json
import os
import urllib.request

OUT = os.path.abspath("checks_out")
os.makedirs(OUT, exist_ok=True)
URL = "https://mcp-api.op.gg/mcp"
session = {}


def rpc(method, params, rid):
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session.get("id"):
        headers["Mcp-Session-Id"] = session["id"]
    req = urllib.request.Request(URL, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=40) as r:
        if r.headers.get("Mcp-Session-Id"):
            session["id"] = r.headers["Mcp-Session-Id"]
        text = r.read().decode("utf-8", "replace")
    if text.lstrip().startswith("{"):
        return json.loads(text)
    for line in text.splitlines():   # server-sent events
        if line.startswith("data:"):
            try:
                return json.loads(line[5:])
            except ValueError:
                pass
    return {"raw": text[:4000]}


out = {}
try:
    out["init"] = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "verse-probe", "version": "1"}}, 1)
    out["tools"] = rpc("tools/list", {}, 2)
    def call(name, args, rid):
        try:
            r = rpc("tools/call", {"name": name, "arguments": args}, rid)
        except Exception as e:
            r = {"error": str(e)}
        out[name + "#" + str(rid)] = r
        return r
    call("lol_get_summoner_profile", {"game_name": "Faker", "tag_line": "KR1", "region": "KR", "lang": "en_US",
         "desired_output_fields": ["data.summoner.league_stats[].tier_info.{border_image_url,division,level,lp,tier,tier_image_url}",
                                   "data.summoner.league_stats[].{game_type,is_fresh_blood,is_hot_streak,is_inactive,is_veteran,lose,series,updated_at,win}"]}, 20)
    for tier in ("emerald", "EMERALD", "emerald_plus"):
        call("lol_get_champion_analysis", {"champion": "JINX", "position": "adc", "game_mode": "ranked", "lang": "en_US", "tier": tier,
             "desired_output_fields": ["data.summary.average_stats.{ban_rate,kda,pick_rate,play,rank,tier,win_rate}",
                                       "data.summary.positions[].stats.{ban_rate,kda,pick_rate,play,role_rate,win_rate}",
                                       "data.summary.positions[].name"]}, 30 + len(tier))
    call("lol_list_champion_leaderboard", {"champion": "JINX", "region": "KR",
         "desired_output_fields": ["leaderboard[].most_champion_stat.{assist,damage_dealt_to_champions,damage_taken,death,double_kill,game_length_second,gold_earned,id,kill,lose,minion_kill,neutral_minion_kill,op_score,penta_kill,play}"]}, 40)
    m = call("lol_list_summoner_matches", {"game_name": "Faker", "tag_line": "KR1", "region": "KR", "lang": "en_US", "limit": 5,
             "desired_output_fields": ["data.game_history[].{created_at,game_length_second,game_map,game_type,id}",
                                       "data.game_history[].average_tier_info.{border_image_url,division,tier}"]}, 50)
    try:
        text = json.dumps(m)
        import re
        gid = re.search(r'\\?"id\\?":\s*\\?"([A-Za-z0-9_=%-]{8,})', text)
        made = re.search(r'\\?"created_at\\?":\s*\\?"([^"\\]+)', text)
        if gid:
            call("lol_get_summoner_game_detail", {"region": "KR", "lang": "en_US", "game_id": gid.group(1),
                 "created_at": made.group(1) if made else None, "focus_riot_id": "Faker#KR1"}, 60)
    except Exception as e:
        out["detail_error"] = str(e)
except Exception as e:
    out["error"] = str(e)
with open(os.path.join(OUT, "opgg.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print("opgg probe:", {k: (len(json.dumps(v)) if v else 0) for k, v in out.items()})
