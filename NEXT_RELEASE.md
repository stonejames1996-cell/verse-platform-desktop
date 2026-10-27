# Next release (held changes)

Changes that are in `main` but not released yet. When it's time to release, bump `APP_VERSION`,
turn these into `release-notes/<version>.md`, then clear this list.

## For the release notes
* **Your highlight is now in the clip too:** when Verse saves a highlight like a Double kill or an Ace, the clip shows the "Clipped by Verse Platform" tag first, then a matching "Double kill" card right when the moment happens. It's part of the video, so it shows on Verse, Discord, TikTok and everywhere else.
* Trimmed and vertical copies keep the card as long as the big moment is still in them.

## Behind the scenes
* Highlight clips now store `moment_from_end` (highlight_after + 0.5s), and `watermark.highlight_png_for`
  draws a 2.6s card in the same style ("CS2 HIGHLIGHT" over the label, "+" in cyan for combos).
* It's placed at the moment, but never on top of the Clipped by tag or cut off by the end of the clip.
  Clips saved with the hotkey, death reviews and squad POVs don't get one.

## Still to confirm on a real PC
* Link Xbox pop-up end to end (log lines: "Sign-in pop-up opened", "Sign-in finished, refreshing Verse").
* New "Clipped by" tag and save pop-up look right in real clips and games (1.2.7).
* Highlight card lands at the right moment in real CS2, Dota 2 and League highlights.
