# Next release (held changes)

Changes that are in `main` but not released yet. When it's time to release, bump `APP_VERSION`,
turn these into `release-notes/<version>.md`, then clear this list.

## For the release notes
* **Link Xbox without leaving the app:** clicking Link Xbox on your Verse profile now opens Microsoft's sign-in in a small pop-up. Once you approve, it closes by itself and your profile refreshes with your gamertag.

## Behind the scenes
* New `Api.open_sign_in(url)` (Verse pages only). Opens a pop-up for Microsoft sign-in addresses only
  (login.microsoftonline.com, login.live.com), with no js_api. It watches the address, and once it's back on
  Verse (any page outside /functions/), it closes and loads that page in the main window. Gives up after 15 minutes.
* Needs the matching Base44 change: the Link Xbox button calls `window.pywebview.api.open_sign_in(url)` when it
  exists and falls back to the normal redirect when it returns false or isn't there.

## Still to confirm on a real PC
* Link Xbox pop-up end to end (log lines: "Sign-in pop-up opened", "Sign-in finished, refreshing Verse").
