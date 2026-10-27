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
    missing = sorted({i for need in lol_items.OPTIONS.values() for ids in need.values() for i in ids
                      if not gd.in_shop(i, 11)})
    print("suggested items not in this patch's Summoner's Rift shop:", missing, [gd.name(i) for i in missing])

print("\nPROBLEMS:" if problems else "\nAll good", *problems, sep="\n  ")
sys.exit(1 if problems else 0)
