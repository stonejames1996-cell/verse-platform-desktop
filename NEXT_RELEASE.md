# Next release (held changes)

Changes that are in `main` but not released yet. When it's time to release, bump `APP_VERSION`,
turn these into `release-notes/<version>.md`, then clear this list.

* WoW: Forever is now recognised by name. Blizzard uses the same Wow.exe for every WoW, so the app checks the install
  folder: `_forever_` = "WoW: Forever" (also `_classic_era_` = WoW Classic Era, `_classic_` = WoW Classic). Clips get the
  right game name instead of "World of Warcraft". (`rewind_core.FOLDER_GAMES`, `GameWatcher.folder_name`)

* World of Warcraft auto highlights (`wow.py`), from WoW's own combat log (player types /combatlog in chat; the app
  only reads `<WoW folder>\_forever_\Logs\WoWCombatLog*.txt`). Clips: boss kills, boss wipes (off), big pulls (4+ mobs
  within 6s), biggest hit and biggest heal of the session (new best crit, at least 1.5x the usual, max one per 3 min),
  killing blows on enemy players plus double/triple/quadra/penta, deaths (off, also feeds death review). One Settings
  section "World of Warcraft" covers Forever, Classic and retail. Session folder in My clips. A reminder pops up if no
  combat log is being written after 90s. The per game highlight cap counts per hour for WoW.
  Checked 5 Nov against W's first Forever log (COMBAT_LOG_VERSION 22, build 1.60.1): time stamps, damage and heal
  amounts read right; Forever logs most deaths without PARTY_KILL, so a unit dying within 6s of my hit counts as my kill.
  Still to check: the player's own lines (flag 0x511) and a crit; W's first log had none of his own actions.

## Still to confirm on a real PC
* WoW highlights with a real Forever combat log (log lines "WoW highlights: reading ...", "WoW: boss down ...",
  "World of Warcraft highlight moment: ..."), and that crits are read right (biggest hit numbers match the game).
* WoW: Forever clips are tagged "WoW: Forever" (log: "Recording WoW: Forever" or similar when the game starts).
* 1.4.0 (paused page CONFIRMED on W's PC 5 Nov with WoW: Forever; still to check: back to same page after, Open anyway, minimise): window swaps to the paused page when a game starts (log "Window paused while ... is on"), goes back to the
  same page when it ends ("Window back from pause"), Open anyway sticks for that game, minimising unloads the page
  ("Window minimized, page unloaded"). Resource use lines should say "paused for the game" with tiny window numbers.
* 1.3.9: League FPS steadier with the stats box up; window reopens on the right page after closing to tray;
  "Resource use" lines in the log (window MB should drop to near nothing once closed to the tray).
* 1.3.8: The Finals elimination card shows top left in game and in clips, no second card burned on auto clips.
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
* The Finals highlights in real matches (log: "Reading The Finals's on-screen pop-ups", "The Finals: elimination",
  "The Finals banner not understood: ..." shows cashout wording we don't know yet). Try 1080p and 1440p.
* The Finals elimination pop-ups, box and session summary in a real game; pop-ups show in clips, box doesn't.
* Per-game highlight switches: turning one off in one game leaves the others alone.
* Per-game shortcuts in real games: The Finals' keys only act in The Finals, League's in League.
* 1.3.6: the save pop-up appears in a clip saved within 60s of another one, and Settings groups open and close.
* 1.3.4: dragging overlays in move mode in a real game, the new chart and closed analysis in My clips.
