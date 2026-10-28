"""
Quick checks that run on the Windows build machine (GitHub Actions) before each build:
  * screen helpers: find the screen of a window, match it to Desktop Duplication's numbering
  * FFmpeg: can gfxcapture aim at a screen by handle (hmonitor=)?
  * League item ideas: load Riot's game data and draw the pop-up for a made-up match
Writes what it finds to checks_out/ (uploaded with the build, handy for eyeballing the pop-up).
"""
import ctypes
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.abspath("checks_out")
os.makedirs(OUT, exist_ok=True)

import rewind_core as rc   # noqa: E402

problems = []

# ---- screens
u = ctypes.WinDLL("user32")
u.GetDesktopWindow.restype = ctypes.c_void_p
desk = u.GetDesktopWindow()
hmon = rc.monitor_of(desk)
print("desktop window screen:", hmon, rc.screen_name(hmon), rc.screen_rect(hmon))
idx = rc.dxgi_output_index(hmon)
print("Desktop Duplication output for it:", idx)
if not hmon or not rc.screen_rect(hmon):
    problems.append("couldn't find the screen of a window")
wins = rc.visible_windows()
print("visible windows:", len(wins), [(w.exe, w.hwnd, w.area) for w in wins[:5]])

ff = os.path.abspath(os.path.join("build_deps", "ffmpeg.exe"))
if os.path.exists(ff) and hmon:
    for src in (f"gfxcapture=hmonitor={hmon}:max_framerate=30", "gfxcapture=monitor_idx=0:max_framerate=30",
                f"ddagrab=output_idx={idx if idx is not None else 0}:framerate=30"):
        r = subprocess.run([ff, "-hide_banner", "-f", "lavfi", "-i", src, "-frames:v", "2",
                            "-vf", "hwdownload,format=bgra", "-f", "null", "-"], capture_output=True, text=True)
        print(f"ffmpeg {src}: exit {r.returncode} {r.stderr.strip()[-160:]}")
    r = subprocess.run([ff, "-hide_banner", "-h", "filter=gfxcapture"], capture_output=True, text=True)
    print("gfxcapture knows hmonitor:", "hmonitor" in r.stdout)
    if "hmonitor" not in r.stdout:
        problems.append("this FFmpeg's gfxcapture has no hmonitor option (falls back to screen numbers)")

# ---- item ideas
import lol_items  # noqa: E402

gd = lol_items.GameData(OUT)
if not gd.ensure():
    problems.append("couldn't load Riot's item data")
else:
    sample = json.load(open(os.path.join(os.path.dirname(__file__), "sample_lol_game.json"), encoding="utf-8"))
    res = lol_items.ideas(gd, sample)
    print("item ideas:", json.dumps(res, indent=1))
    if not res:
        problems.append("no item ideas for the sample match")
    else:
        for row in res["rows"]:
            print(" ", row["why"], "->", [gd.name(i) for i in row["items"]])
        for scale in (1.0, 1.5):
            lol_items.render(gd, res, scale).save(os.path.join(OUT, f"item_ideas_{scale}.png"))
        # the full panel while you're dead, the timers strip and the match summary (lol_live)
        import lol_live
        me = lol_live.me_in(sample)
        hist = lol_live.History(OUT)
        for i in range(6):
            hist.add({"id": f"g{i}", "rift": True, "role": "BOTTOM", "minutes": 30, "cs_min": 6.2 + i * 0.1,
                      "kp": 0.45, "vision_min": 0.6})
        nums = lol_live.live_numbers(sample, me)
        extras = {"stats": lol_live.stat_tiles(nums, hist.averages("BOTTOM", True)),
                  "gold": lol_live.lane_gold(gd, sample, me)}
        print("your game:", nums, extras["gold"])
        lol_items.render(gd, res, 1.5, extras).save(os.path.join(OUT, "panel_1.5.png"))
        timers = lol_live.ObjectiveTimers()
        timers.update(sample, me["team"])
        rows = timers.active(float(sample["gameData"]["gameTime"]))
        print("timers:", rows)
        lol_live.render_timers(rows, 1.5).save(os.path.join(OUT, "timers_1.5.png"))
        for g in hist.games:
            g.update({"gpm": 380.0, "kda": 2.8})
        bench = lol_live.bench_rows(nums, hist.averages("BOTTOM", True),
                                    lol_live.gold_per_min(gd, sample, me, nums["minutes"]), 9,
                                    [5.1, 5.8, 6.2, 6.0, 6.9, 7.2, 7.5], gd.champ_icon("Kaisa", 64))
        print("benchmarks:", bench)
        lol_live.render_strip(bench, rows, 1.5).save(os.path.join(OUT, "strip_1.5.png"))
        summ = {"result": "Win", "champion": "Jinx", "champion_key": "Jinx", "kills": 9, "deaths": 3, "assists": 11,
                "cs": 231, "cs_min": 7.7, "kp": 0.64, "vision": 31, "better": ["CS", "kill share"], "clips": 3}
        lol_live.render_summary(gd, summ, 1.5).save(os.path.join(OUT, "summary_1.5.png"))
        if not rows or not extras["gold"]:
            problems.append("timers or lane gold came out empty for the sample match")
    missing = sorted({i for need in lol_items.OPTIONS.values() for ids in need.values() for i in ids
                      if not gd.in_shop(i, 11)})
    print("suggested items not in this patch's Summoner's Rift shop:", missing, [gd.name(i) for i in missing])

# ---- OP.GG (rank comparisons in the match analysis)
try:
    import opgg
    from datetime import datetime
    o = opgg.OPGG(OUT)
    prof = o.profile("Faker#KR1", "KR")
    at = o.champion_at_tier("Jinx", "BOTTOM", (prof or {}).get("tier") or "EMERALD")
    top = o.top_players("Jinx", "OCE")
    print("opgg profile:", prof)
    print("opgg Jinx at tier:", at)
    print("opgg top Jinx OCE:", top)
    hist = o.call("lol_list_summoner_matches", {"game_name": "Faker", "tag_line": "KR1", "region": "KR", "lang": "en_US",
                  "limit": 5, "desired_output_fields": ["data.game_history[].{created_at,id}",
                  "data.game_history[].participants[].{champion_name}"]}, 60)
    g0 = (((hist or {}).get("data") or {}).get("game_history") or [None])[0]
    if g0:
        ts = datetime.fromisoformat(g0["created_at"]).timestamp()
        champ = ((g0.get("participants") or [{}])[0]).get("champion_name")
        print("opgg recent game:", o.recent_game("Faker#KR1", "KR", ts + 60, champ))
    if not (prof and at and top):
        problems.append("OP.GG answers missing (profile / champion at tier / top players)")
except Exception as e:
    problems.append(f"OP.GG check crashed: {e}")

print("\nPROBLEMS:" if problems else "\nAll good", *problems, sep="\n  ")
sys.exit(1 if problems else 0)
