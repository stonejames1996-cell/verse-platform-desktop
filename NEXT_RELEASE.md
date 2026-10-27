# Next release (held changes)

Changes that are in `main` but not released yet. When it's time to release, bump `APP_VERSION`,
turn these into `release-notes/<version>.md`, then clear this list.

## For the release notes
* **Live benchmarks for League:** a small box on the right shows how your game is going compared with your own average: CS per minute (with a little line of how it's moved this game), gold per minute, kill share and K/D/A, plus your level vs your lane opponent. Green means above your usual, yellow below. Your average builds up after 3 games. Never shows in your clips.
* **Objective timers for League:** a small box on the right counts down when Dragon, Elder Dragon, Baron and inhibitors come back, and says when they're up. It only uses the kill announcements everyone sees, and never shows in your clips.
* **Your game so far:** the pop-up while you're dead now also shows your CS per minute, kill share and vision compared with your own average from past games, plus your items' gold vs the enemy in your lane (like "1,350 behind Kai'Sa").
* **Match summary:** when a League game ends you get a summary card with your K/D/A, CS, kill share and vision, what you did better than usual, and how many highlights were saved. The same numbers show on that game in My clips, with a button to post its best clip.
* Each of these can be switched off in Settings under League of Legends in game.

## Behind the scenes
* New `lol_live.py`: `LeagueCompanion` replaces `lol_items.ItemIdeas` (one loop on `/allgamedata` a second).
  `ObjectiveTimers` reads DragonKill (soul at 4 of a team's dragons -> Elder 6:00, else 5:00), BaronKill (6:00),
  InhibKilled/InhibRespawned (5:00). No enemy cooldowns (Riot bans that). Shown by a second `Overlay` window
  ("VersePlatformTimers", `show_static`, right side, kept out of clips).
* Your own averages: `lol_history.json` in the data folder (last 200 games, 10+ minutes), last 20 of the same
  kind (Summoner's Rift or not), same role when there are 5+. Lane gold uses `position` from the live data.
* Match summary saved as `summary` on the match (`library.save_match` now merges fields), shown in the match card.
* Settings: `lol_objective_timers`, `lol_benchmarks`, `lol_match_summary` (on), `lol_item_ideas` now covers the whole panel.
* Benchmarks share the timers' window (`render_strip`). Gold per minute is an estimate: item value + current gold
  over game minutes (League's live data has no gold earned). History now also keeps `gpm` and `kda`.

## Still to confirm on a real PC
* Link Xbox pop-up end to end (log lines: "Sign-in pop-up opened", "Sign-in finished, refreshing Verse").
* New "Clipped by" tag and save pop-up look right in real clips and games (1.2.7).
* Highlight card lands at the right moment in real CS2, Dota 2 and League highlights.
* League item ideas pop-up in a real match (log: "Item ideas shown: ..."), in borderless mode.
* Recording follows the game to a second screen (log: "Recording the game's screen (DISPLAY2 ...)").
* Objective timers line up with the in-game times (Dragon 5:00, Elder/Baron 6:00, inhibitors 5:00 on patch 16.21).
* Match summary card and the My clips match summary after a real League game.
