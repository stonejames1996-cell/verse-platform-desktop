# Next release (held changes)

Changes that are in `main` but not released yet. When it's time to release, bump `APP_VERSION`,
turn these into `release-notes/<version>.md`, then clear this list.

## For the release notes
* **Move the overlays:** press Alt+Shift+M in game, drag the stats box, the stats and item ideas pop-up, and the save and summary pop-ups wherever you like, then press it again to save. They stay put between games and on other screen sizes, and Settings has a Reset spots button.
* **Match analysis, tidied up:** it's now closed by default, showing just your three scores. Click it to open the full analysis.
* **A better chart:** smooth lines with a glow, the game's lane, mid and late phases marked, champion pictures and numbers at the end of each line, and hover anywhere to see everyone's numbers at that minute. Text stays the same size however wide the window is.
* **Champion pictures:** "Compared with" shows your lane opponent's picture, and the chart's key shows yours and theirs.
* **Clearer lane tips:** when you catch up on your lane opponent but finish just behind, it now says you closed the gap instead of saying you pulled ahead.
* **Hide the stats box:** press Alt+Shift+B in League to hide the box on the right (benchmarks and timers), and again to bring it back. A short message confirms it, it stays the way you left it next game, and you can pick your own keys in Settings.
* **Tidier stats pop-up:** the "building your average" text no longer spills out of the boxes. Until you've played 3 games there's one short line under them instead, and any long text in a box now shrinks to fit.

## Behind the scenes
* Move mode: `overlay.MoveMode` opens one draggable layered window per overlay (WM_NCHITTEST -> HTCAPTION, no focus
  steal), saves `overlay_positions` {"strip","panel","popup": [x, y] screen shares}; `Overlay._present` uses them
  (clamped to the screen). `overlay_move_hotkey` (alt+shift+m), `Api.reset_overlay_positions`. The companion pauses the
  strip while moving. Checked on the build machine (open, close, spots read back); dragging itself needs a real PC.
* Match analysis UI: `analysisOpen` (closed by default), `lineChart` redrawn at real pixel width via ResizeObserver,
  monotone smooth paths, phase bands, end labels with champion pictures, hover read-out. Analysis keeps `opp_key`.
* `lol_box_hotkey` (alt+shift+b) toggles `lol_box_visible` (saved in config) via `App.toggle_lol_box`; the companion
  hides the strip when it's off. All three shortcuts are checked against each other in `set_setting`.
* `stat_tiles` marks tiles `new` (no average yet) instead of writing text into them; `lol_items.render` adds one note line,
  makes the tiles shorter when there's no "avg" line, and trims any tile text to the tile width.


## Still to confirm on a real PC
* Link Xbox pop-up end to end (log lines: "Sign-in pop-up opened", "Sign-in finished, refreshing Verse").
* New "Clipped by" tag and save pop-up look right in real clips and games (1.2.7).
* Highlight card lands at the right moment in real CS2, Dota 2 and League highlights.
* League item ideas pop-up in a real match (log: "Item ideas shown: ..."), in borderless mode.
* Recording follows the game to a second screen (log: "Recording the game's screen (DISPLAY2 ...)").
* Objective timers line up with the in-game times (Dragon 5:00, Elder/Baron 6:00, inhibitors 5:00 on patch 16.21).
* Match summary card and the My clips match summary after a real League game.
* Live benchmarks box and objective timers in a real League match (borderless), timings vs the game's own.
* OP.GG: the server is read from League's settings file (log "OP.GG: region OCE, rank ..."), and gold/damage
  arrive a few minutes after the game ("OP.GG has the match").
* Match analysis in My clips after a real game (needs games played on 1.3.0; "your usual" needs 3).
* 1.3.1 icons: objective icons and dragon element in a real match, lane opponent picture, game logos in My clips.
* 1.3.2: changing the stats and item ideas shortcut in Settings, and that it works in game.
* 1.3.4: dragging overlays in move mode in a real game, the new chart and closed analysis in My clips.
