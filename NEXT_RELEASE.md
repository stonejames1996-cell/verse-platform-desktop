# Next release (held changes)

Changes that are in `main` but not released yet. When it's time to release, bump `APP_VERSION`,
turn these into `release-notes/<version>.md`, then clear this list.

## Held
* The Finals elimination pop-up is now the League-style highlight card ("THE FINALS HIGHLIGHT" / "Double kill"),
  sized like the clip card and shown exactly where the "Clipped by Verse Platform" card sits (top left). The Finals
  auto clips skip the burned-in highlight card when it's on (`live_card`), so there's never two.

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
* The Finals highlights in real matches (log: "Reading The Finals's on-screen pop-ups", "The Finals: elimination",
  "The Finals banner not understood: ..." shows cashout wording we don't know yet). Try 1080p and 1440p.
* The Finals elimination pop-ups, box and session summary in a real game; pop-ups show in clips, box doesn't.
* Per-game highlight switches: turning one off in one game leaves the others alone.
* Per-game shortcuts in real games: The Finals' keys only act in The Finals, League's in League.
* 1.3.6: the save pop-up appears in a clip saved within 60s of another one, and Settings groups open and close.
* 1.3.4: dragging overlays in move mode in a real game, the new chart and closed analysis in My clips.
