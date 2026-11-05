"""
Quick checks that run on the Windows build machine (GitHub Actions) before each build:
  * screen helpers: find the screen of a window, match it to Desktop Duplication's numbering
  * FFmpeg: can gfxcapture aim at a screen by handle (hmonitor=)?
  * League item ideas: load Riot's game data and draw the pop-up for a made-up match
  * The Finals: read made-up highlight banners with Windows' text recognition
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

# ---- moving the overlays (Alt+Shift+M): open the drag boxes, close them, check the spots come back
try:
    import threading
    import time as _t
    from overlay import MoveMode
    r = rc.screen_rect(hmon) or (0, 0, 1024, 768)
    for attempt in (1, 2, 3):   # several times in one run: the second time used to crash the app
        got = {}
        done = threading.Event()
        mm = MoveMode(lambda: r, {"panel": [0.5, 0.4]}, lambda pos: (got.update(pos or {}), done.set()))
        _t.sleep(1.5)
        mm.stop()
        done.wait(10)
        print(f"move mode spots (try {attempt}):", got)
    mm._card("Stats box", 170, 270, 1.5).save(os.path.join(OUT, "move_card.png"))
    if not got or abs(got.get("panel", [0, 0])[0] - 0.5) > 0.02:
        problems.append(f"move mode didn't give the spots back: {got}")
except Exception as e:
    problems.append(f"move mode check crashed: {e}")

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

# ---- The Finals: read made-up banners with Windows' text recognition, the same way the app does
try:
    import random
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    import finals
    fdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
    big = ImageFont.truetype(os.path.join(fdir, "InterDisplay-Bold.otf"), 34)
    small = ImageFont.truetype(os.path.join(fdir, "InterDisplay-Bold.otf"), 26)

    def frame_1080(top, bottom, bg):
        """A 1920x1080 'game' picture with a Finals-style banner under the crosshair (italic, white/red/yellow)."""
        rnd = random.Random(bg)
        im = Image.new("RGB", (1920, 1080), [(30, 40, 60), (150, 160, 190), (90, 60, 40)][bg])
        d = ImageDraw.Draw(im)
        for _ in range(400):   # busy scenery
            x, y = rnd.randrange(1920), rnd.randrange(1080)
            c = tuple(min(255, v + rnd.randrange(-60, 60)) for v in im.getpixel((x, y)))
            d.rectangle((x, y, x + rnd.randrange(10, 120), y + rnd.randrange(10, 80)), fill=c)
        im = im.filter(ImageFilter.GaussianBlur(2))
        text = Image.new("RGBA", (1920, 200), (0, 0, 0, 0))
        td = ImageDraw.Draw(text)
        x = 960 - sum(td.textlength(t + "  ", font=big) for t, _ in top) / 2
        for t, col in top:
            td.text((x, 30), t, font=big, fill=col, stroke_width=1, stroke_fill=(0, 0, 0))
            x += td.textlength(t + "  ", font=big)
        bw = td.textlength(bottom, font=small)
        td.text((960 - bw / 2, 80), bottom, font=small, fill=(232, 226, 60), stroke_width=1, stroke_fill=(0, 0, 0))
        text = text.transform(text.size, Image.AFFINE, (1, 0.2, -20, 0, 1, 0))   # italic slant
        im.paste(text, (0, 660), text)
        return im

    W, R, Y = (240, 240, 240), (230, 40, 60), (232, 226, 60)
    samples = [
        ([("ELIMINATED", W), ("SEERKING", R), ("$100", Y)], "ELIMINATION | + 250", 0, "elim"),
        ([("ELIMINATED", W), ("XxDarkWolf_99", R), ("$100", Y)], "ELIMINATION | + 250", 1, "elim"),
        ([("TEAM WIPE", W), ("BONUS", Y)], "ELIMINATION 250 + 696", 2, "wipe"),
        ([("TEAM STOLE A CASHOUT", W), ("BONUS", Y), ("$1,000", Y)], "ASSIST + 600", 1, "steal"),
    ]
    # run the frames through FFmpeg with the recorder's own crop, so the banner position is checked too
    ff = os.path.abspath(os.path.join("build_deps", "ffmpeg.exe"))
    ocr = finals.WindowsOcr()
    ok = 0
    for i, (top, bottom, bg, want) in enumerate(samples):
        src = os.path.join(OUT, f"finals_frame_{i}.png")
        frame_1080(top, bottom, bg).save(src)
        if os.path.exists(ff):
            raw = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-i", src, "-vf", rc.TAP_CROP,
                                  "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
            crop = Image.frombytes("L", (rc.TAP_W, rc.TAP_H), raw[:rc.TAP_W * rc.TAP_H])
        else:
            crop = Image.open(src).convert("L").crop((480, 594, 1440, 810))
        crop.save(os.path.join(OUT, f"finals_tap_{i}.png"))
        lines, got = [], []
        for v, version in enumerate(finals.prepare(crop)):
            read = ocr.read(version)
            lines.append(f"v{v}: {read}")
            got = finals.parse(read)
            if got:
                break
        hit = [g[0] for g in got] == [want]   # exactly the one moment, no made-up extra kills
        ok += hit
        print(f"finals sample {i} want={want} bright={finals.has_bright_text(crop)} got={got}", *lines, sep="\n   ")
    print(f"finals: {ok}/{len(samples)} banners read right (OCR available: {ocr.ok})")
    import finals_overlay as fo
    fo.render_title(2, False, 200).save(os.path.join(OUT, "finals_title.png"))
    got_icons = {k: fo.game_icon(k) is not None for k in fo.GAME_ICONS}
    print("finals game icons downloaded:", got_icons)
    if not all(got_icons.values()):
        problems.append(f"The Finals icons didn't download: {got_icons}")
    fo.render_box({"elims": 14, "wipes": 2, "cashouts": 3, "steals": 1, "best": 3, "cash": 4300}, 1.25).save(os.path.join(OUT, "finals_box.png"))
    fo.render_summary({"elims": 14, "wipes": 2, "cashouts": 3, "steals": 1, "best": 3, "cash": 4300, "minutes": 47},
                      {"elims": 11.2, "wipes": 2, "cashouts": 1.5, "steals": 1.4, "best": 2.2, "cash": 3100}, 1.25).save(os.path.join(OUT, "finals_summary.png"))
    # big copies for promo graphics
    fo.render_box({"elims": 14, "wipes": 2, "cashouts": 3, "steals": 1, "best": 3, "cash": 4300}, 3).save(os.path.join(OUT, "finals_box_big.png"))
    fo.render_summary({"elims": 14, "wipes": 2, "cashouts": 3, "steals": 1, "best": 3, "cash": 4300, "minutes": 47},
                      {"elims": 11.2, "wipes": 2, "cashouts": 1.5, "steals": 1.4, "best": 2.2, "cash": 3100}, 3).save(os.path.join(OUT, "finals_summary_big.png"))
    print("finals overlays drawn")
    if ok < len(samples):
        problems.append(f"The Finals banners: only {ok}/{len(samples)} read right")
except Exception as e:
    import traceback
    traceback.print_exc()
    problems.append(f"The Finals check crashed: {e}")

# https certificates checked by Windows itself (truststore), like the app does for updates
try:
    import time, truststore, urllib.request
    truststore.inject_into_ssl()
    with urllib.request.urlopen("https://api.github.com/repos/stonejames1996-cell/verse-platform-desktop/releases/latest", timeout=20) as r:
        print("truststore https ok:", r.status)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import rewind_core as rc
    print("calm game WoW: Forever:", rc.is_calm_game("WoW: Forever"), "League:", rc.is_calm_game("League of Legends"),
          "input since 1h ago:", rc.input_since(time.time() - 3600))
except Exception as e:
    import traceback
    traceback.print_exc()
    problems.append(f"truststore / calm check failed: {e}")

print("\nPROBLEMS:" if problems else "\nAll good", *problems, sep="\n  ")
sys.exit(1 if problems else 0)
