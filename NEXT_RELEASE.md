# Next release (held changes)

Changes that are in `main` but not released yet. When it's time to release, bump `APP_VERSION`,
turn these into `release-notes/<version>.md`, then clear this list.

## Held
* The "Last 60s saved by Verse Platform" pop-up is always on now (the Settings switch is gone) and it shows up
  in recordings, so Verse is seen in people's clips. Error pop-ups and other notices still stay out of clips.
* Settings: every group starts closed, showing an icon, its name and a one-line summary. Click to open it.
  Open and Close all buttons, groups remember if you left them open, and they sit in two fixed columns so
  opening one never moves the others.
* The Finals auto highlights (new). The game has no data feed for apps, so the app reads its own
  pop-ups under the crosshair with Windows' built-in text recognition: "ELIMINATED <name>" (double,
  triple, quad kill, and Multi-kill for 5 or more, each within 6s of the last), "TEAM WIPE", "TEAM STOLE A CASHOUT" and your team's
  cashout. New Settings switches under Auto highlights: Team wipe, Cashout, Cashout steal. The Finals is
  now recognised by name (Discovery.exe with the "THE FINALS" window) and has its logo in My clips.
* The Finals overlays (finals_overlay.py), each with its own switch in The Finals' Settings section:
  - Elimination pop-ups: the League-style pop-up on each elimination with its title (Elimination, Double kill,
    Triple kill, Quad kill, Multi-kill, Team wipe) and the cash won. Shows in clips. Movable with Alt+Shift+M
    (new "Elimination pop-up" box).
  - The box and summary use the game's own icons (eliminated contestant, cashout station, cashbox, coins),
    downloaded by the app from THE FINALS Wiki on first use and cut out (not in this repo); drawn icons if offline.
  - Your game so far: eliminations, team wipes, cashouts, steals, best multi kill, cash earned. Uses the
    stats box spot and the Alt+Shift+B hide shortcut. Never in clips.
  - Session summary: when the game closes, vs your usual (after 3 sessions of 5+ min, finals_history.json).
  - Each session is a folder in My clips with the summary on top.
* Settings: a section per game (League of Legends, The Finals, Counter-Strike 2, Dota 2), each with its OWN
  highlight switches (highlight_events is now {game: {...}}; old shared settings carry over to every game).
  Auto highlights keeps the main switch, clip length, death reviews and the per-game limit.

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
* Next release: the save pop-up appears in a clip saved within 60s of another one, and Settings groups open and close.
* 1.3.4: dragging overlays in move mode in a real game, the new chart and closed analysis in My clips.
