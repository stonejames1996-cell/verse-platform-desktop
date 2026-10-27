# Next release (held changes)

Changes that are in `main` but not released yet. When it's time to release, bump `APP_VERSION`,
turn these into `release-notes/<version>.md`, then clear this list.

## For the release notes
* **A sleeker "Clipped by Verse Platform":** the tag at the start of your clips has a fresh premium look. It glides in with a cyan accent and a quick shine, and now stays on screen for 3 seconds instead of 2.

## Behind the scenes
* `watermark.py` now draws a 3s animated title card (90 PNG frames at 30fps, cached per video height in
  %TEMP%/VersePlatformWatermark/v2_<height>) and overlays it as an image sequence. Same `png_for`/`inputs`/
  `filter_graph` interface, so library.py export, vertical export and the background watermark job are unchanged.
* Bundles Inter (InterDisplay-Bold, Inter-SemiBold, SIL OFL, licence in assets/fonts/OFL.txt) so the card looks
  the same on every PC. Falls back to Segoe UI if the fonts are missing.
* Clips that were already watermarked keep the old 2s tag; only new clips get the new one.


## Still to confirm on a real PC
* Link Xbox pop-up end to end (log lines: "Sign-in pop-up opened", "Sign-in finished, refreshing Verse").
