# Next release (held changes)

Changes that are in `main` but not released yet. When it's time to release, bump `APP_VERSION`,
turn these into `release-notes/<version>.md`, then clear this list.

## For the release notes
* **Rank icons:** the lobby's average rank in a League game's summary now shows its rank icon (like the Platinum crest), not just the name.
* **Objective icons:** the timers in League now use the game's own icons for Dragon, Elder Dragon, Baron and inhibitors. Once the rift's element is set, the next dragon shows its element too, like "Ocean Dragon".
* **Lane opponent picture:** the level line in the benchmarks box shows your lane opponent's champion next to their level.
* **Pictures in the match analysis:** your champion sits on the score card, and lines that compare you with your rank or with top players show the rank crest or champion picture.
* **Game logos in My clips:** the game filter tabs and game headings now show each game's logo.

## Behind the scenes
* Riot's minimap icons (from CommunityDragon) are bundled in `assets/lol` (in the PyInstaller spec); `lol_live.lol_icon()`
  loads them. Timer `kind` is now the icon name. Dragon element: from the 3rd elemental dragon on, the next one is the
  3rd one's type (DragonType Fire/Earth/Water/Air/Chemtech/Hextech -> Infernal/Mountain/Ocean/Cloud...).
* Game logos are bundled in `ui/games/<slug>.png` (site favicons). Apex, Call of Duty and Elden Ring only gave the
  publisher's logo, so they (and any game without a file) get a letter badge.
* `opgg.recent_game` adds `lobby_image` (OP.GG medal `medals_new/<tier>.png`); `lobbyStat()` in ui/app.js shows it,
  building the same URL from the tier name for games saved on 1.3.0.


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
