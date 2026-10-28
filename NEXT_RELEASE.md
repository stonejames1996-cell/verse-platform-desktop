# Next release (held changes)

Changes that are in `main` but not released yet. When it's time to release, bump `APP_VERSION`,
turn these into `release-notes/<version>.md`, then clear this list.

## For the release notes
* **Sharper game logos:** League of Legends, Counter-Strike 2 and Apex Legends now have proper high quality logos in My clips (Apex had a letter badge before).

## Behind the scenes
* `ui/games/league-of-legends.png`, `counter-strike-2.png`, `apex-legends.png` replaced with 128px versions of the logos W sent
  (League's faint smoke trimmed). `GAME_LOGOS` in ui/app.js now includes apex-legends.


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
