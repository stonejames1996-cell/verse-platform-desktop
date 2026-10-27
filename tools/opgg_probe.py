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
    calls = {
        "lol-champion-analysis": {"champion": "JINX", "game_mode": "ranked", "lang": "en_US", "position": "adc"},
        "lol-champion-positions-data": {"lang": "en_US"},
        "lol-summoner-search": {"game_name": "Faker", "tag_line": "KR1", "region": "kr", "lang": "en_US"},
        "lol-summoner-game-history": {"game_name": "Faker", "tag_line": "KR1", "region": "kr", "lang": "en_US"},
    }
    for i, (name, args) in enumerate(calls.items()):
        try:
            out[name] = rpc("tools/call", {"name": name, "arguments": args}, 10 + i)
        except Exception as e:
            out[name] = {"error": str(e)}
except Exception as e:
    out["error"] = str(e)
with open(os.path.join(OUT, "opgg.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print("opgg probe:", {k: (len(json.dumps(v)) if v else 0) for k, v in out.items()})
