# Next release (held changes)

Changes that are in `main` but not released yet. When it's time to release, bump `APP_VERSION`,
turn these into `release-notes/<version>.md`, then clear this list.

## For the release notes
* **League item ideas:** when you die in League, a small pop-up suggests counter items based on what the enemy team has, like anti heal against Soraka and Aatrox or armour against a fed Kai'Sa. It always gives you a few choices with the reason, and it disappears when you respawn. Press Alt+Shift+I in a match to see it any time. It uses the same info as the Tab screen, and if you clip while it's open it shows in the clip too. You can turn it off in Settings.
* **Records the screen your game is on:** with more than one screen, Verse now records whichever one the game is open on, even if you move it mid game. Save pop-ups show up on that screen too. You can turn this off in Settings and pick a screen yourself.

## Behind the scenes
* `lol_items.py`: reads `/allgamedata` from the Live Client Data API, item and champion data from Data Dragon
  (cached per patch in `%APPDATA%\Verse Platform\lol_data`). Ideas need at least 2 item choices per row,
  never win rates, skips Arena/TFT/Swarm. Shown via `Overlay.show_image` on the left middle of the screen
  while you're dead (gone on respawn), or 12s on `item_ideas_hotkey`. Settings: `lol_item_ideas`.
* Screen following: `GameWatcher.game_window` -> `monitor_of(hwnd)` -> `Recorder.follow_screen(hmon)`.
  gfxcapture uses `hmonitor=`, ddagrab gets its `output_idx` from DXGI (`dxgi_output_index`), gdigrab is
  cropped to that screen. Capture restarts when the game changes screen. Setting `follow_game_screen` (on).
* Build: a "Windows checks" step (`tools/win_checks.py`) tests the screen helpers, FFmpeg's gfxcapture options
  and item ideas on a sample match, and saves results to the `ci-checks` branch (log.txt and the pop-up picture).
  It never blocks a release. Checked on patch 16.21.1: every suggested item exists, DXGI matching works.

## Still to confirm on a real PC
* Link Xbox pop-up end to end (log lines: "Sign-in pop-up opened", "Sign-in finished, refreshing Verse").
* New "Clipped by" tag and save pop-up look right in real clips and games (1.2.7).
* Highlight card lands at the right moment in real CS2, Dota 2 and League highlights.
* League item ideas pop-up in a real match (log: "Item ideas shown: ..."), in borderless mode.
* Recording follows the game to a second screen (log: "Recording the game's screen (DISPLAY2 ...)").
