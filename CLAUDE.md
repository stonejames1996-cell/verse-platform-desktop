# Verse Platform for Windows: handover for Claude

Read this first. It's everything a new Claude (or person) needs to keep working on this app.

## What this is
The Windows desktop app for **Verse Platform** (verseplatform.gg), a gaming clip-sharing site built in Base44
(app id `695f8fed3712a7e5ac398069`). The app records the screen in the background like Game Bar or Outplayed,
saves clips on a hotkey or automatically on highlights, and hands clips to the website's Upload page.

- Repo: `stonejames1996-cell/verse-platform-desktop` (public). Owner James, the site owner W is a collaborator.
- Website, mobile app, squad relay and AI captions live in Base44, not here. Changes there are made through the
  Base44 builder chat and only go live when someone clicks **Publish** in Base44.
- Discord: update posts go to #platform-updates automatically (see Releases).

## How the people working on it like things done
- Plain, casual language. Few dashes. No jargon in anything users read.
- **Give patch notes for every change**, in plain bullet points, in the reply.
- **Don't spam releases.** Hold changes and release them in batches. Keep a `NEXT_RELEASE.md` listing held changes.
  Only ship a quick fix on its own after asking, and only when something is properly broken (clips not saving, lag, no sound).
- Never publish Base44 without the owner saying so.
- Never put secrets in the code (the repo is public).
- Use icons wherever we can (rank crests, champion and item pictures, objective icons) instead of plain text.

## Code map (Python 3, PyInstaller, pywebview / WebView2, FFmpeg)
- `verse_desktop.py`: the app. Window, tray, `App` (recording control, save queue, death review, watermark queue,
  overlay, highlights wiring, Squad, auto clean) and `Api` (everything the UI and the Verse website call).
- `rewind_core.py`: config (`%APPDATA%\Verse Platform\config.json`, log `verse_platform.log`), `APP_VERSION`,
  `Recorder` (FFmpeg segment recorder writing 2s .ts chunks to a temp buffer; `save_clip` stitches them).
  Capture: `gfxcapture` (Windows Graphics Capture, default on Windows 11), `ddagrab` (default on 10), `gdigrab` last resort.
  Watchdog restarts capture and switches method if the picture freezes or is starved (Discord screen share starves ddagrab).
  "GPU only" path keeps frames on the GPU for NVENC/AMF (falls back by itself). Sound: WASAPI loopback of the default
  output (`Loopback`), follows default device changes; optional mic gives two tracks (mix, game only).
- `library.py`: clip library (`clips.json`, `matches.json`), thumbnails, trimming/export, vertical export, weekly recap,
  watermark burn-in, stars, storage, Recycle Bin delete, local media server for the UI and Verse.
- `highlights.py`: League of Legends auto highlights via Riot's Live Client Data API (127.0.0.1:2999), match folders.
- `gsi.py`: CS2 and Dota 2 highlights via Valve Game State Integration (writes cfg files, local server on port 3517).
  Dota needs `-gamestateintegration` in Steam launch options.
- `squad.py`: Squad POV. Mates share a squad code, highlights are signalled through the Base44 function
  `https://verseplatform.gg/functions/squadRelay?secret=...`, mates save their own POV, small copies come back and get
  combined side by side. Secret is baked in at build time from the `SQUAD_RELAY_SECRET` repo secret (`squad_secret.txt`, never committed).
- `triggers.py`: "clip that" voice command (Windows System.Speech) and controller combos (XInput).
- `lol_live.py`: League companion loop: objective timers strip, the panel while dead (own stats vs `lol_history.json` averages,
  lane item gold, item ideas), match summary card + `summary` on the match. Riot policy: no enemy cooldowns, no win rates.
- `opgg.py`: OP.GG's public MCP server (mcp-api.op.gg/mcp, same as the website's guides): rank, champion at your tier
  (KDA, win rate), top players (CS/gold per min from leaderboard totals), your real game after (gold, damage, lobby rank).
  Answers are a class-text format, `parse()` reads them. Server from League's LeagueClientSettings.yaml. Cached in opgg_cache.json.
  OP.GG has no per-rank CS/gold averages, so farming compares with your usual and with top players.
- `lol_items.py`: League item ideas pop-up (counter items from enemy items on Tab, Data Dragon names/icons; shown while dead or Alt+Shift+I).
  Keep it inside Riot policy: always 2+ choices with reasons, no win rates, only Tab info.
- `overlay.py`: the "Last 60s saved by Verse Platform" pop-up. `watermark.py`: animated "Clipped by Verse Platform" card for the
  first 3s (always on). Both use the bundled Inter fonts in `assets/fonts` (OFL).
- `updater.py`: auto update from GitHub Releases (`VersePlatformSetup.exe`, sha256 checked, silent install, relaunch).
- `whatsnew.py` + `release-notes/*.md`: the in-app What's new pop-up.
- `ui/`: the My clips / Settings screens (plain HTML/JS/CSS).
- `base44/SETUP.md`: notes on the website side.
- Xbox linking lives in Base44 (functions xboxLinkStart, xboxCallback, xboxUnlink; Azure app "Verse Platform",
  client ID `1a850251-4883-4d41-8cdb-3576bd62b96d`, personal accounts). In the app, Link Xbox opens a sign-in pop-up via
  `Api.open_sign_in` (Microsoft hosts only) that closes and refreshes Verse when done.

## Website features added Oct 2026 (all in Base44, not this repo)
- Account linking on profiles: Xbox (Azure app above), Steam (OpenID, `STEAM_WEB_API_KEY`), Battle.net
  (Blizzard client "Verse Platform", `BATTLENET_CLIENT_ID/SECRET`). Records live in backend-only XboxLink, SteamLink,
  BattlenetLink tables. Riot: production app 897128 pending review, verified via verseplatform.gg/riot.txt.
  Typed Riot IDs do not count as linked; Riot tournaments show "Riot linking coming soon".
- Verse Brackets (Events page, tabs Community / Verse Brackets): tournaments, sign-up, check-in, single elim bracket,
  score reporting, disputes, champion badge, stats card. Hosting is locked to williamclark960@gmail.com.
- Verse Teams (VerseTeam table, separate from the old pro-team "Team" table), invites, team check-in, Looking for team board.
- Preview and live share ONE database. Test tournaments use is_test (host-only, never counted). A finished
  "TEST CS2 Cup" exists for reference; ask the builder to "delete all is_test tournament data" to remove it.
- Not yet tested with real accounts: disputes/30 min timeout, team invites, team sign-up and team check-in.

## Releases (fully automatic)
1. Bump `APP_VERSION` in `rewind_core.py`.
2. Add `release-notes/<version>.md` (plain bullets, user friendly).
3. Commit and push to `main`.
GitHub Actions (`.github/workflows/build.yml`) builds the installer, creates release `v<version>`, posts the notes to
Discord, and every user's app updates itself within ~2 hours. A push without a version bump builds nothing.
Repo secrets used: `DISCORD_WEBHOOK_URL`, optional `DISCORD_PING_ROLE_ID`, `SQUAD_RELAY_SECRET`.
`Release.bat` / `release.ps1` do the same from a Windows PC.

## Windows checks in the build
Every build runs `tools/win_checks.py` on the Windows runner and pushes its results to the `ci-checks` branch
(`log.txt`, rendered item ideas pictures). Read it with `git fetch origin ci-checks` and `git show origin/ci-checks:log.txt`
(the Actions log download is blocked from Claude's sandbox). The runner has no GPU, so actual capture fails there; that's expected.

## Debugging
Ask for `%APPDATA%\Verse Platform\verse_platform.log` (and `crash.log` if there is one) plus a broken clip.
The "Ready." line shows encoder, capture method and "(GPU only)". Useful lines: "Capture froze", "Switching from",
"Sound output changed", "Saved with no audio", "Told the squad".

## Still to confirm on a real PC (as of 1.3.0)
- GPU-only recording ("(GPU only)" in the log, lower FFmpeg CPU in Task Manager).
- Default sound device following ("Sound output changed, recording follows it").
- Squad POV end to end between two PCs (needs the Base44 squadRelay function published; the upload size limit is untested).
- CS2 and Dota 2 highlights in real matches.
- Mobile app iris launch intro on a real phone (lives in Base44).
- Link Xbox pop-up in the app ("Sign-in pop-up opened" then "Sign-in finished, refreshing Verse"). Shipped in 1.2.6, Base44 side published.
- New 3s "Clipped by" card and restyled save pop-up (1.2.7) in real clips and games.
- Highlight card (e.g. "Double kill") landing at the right moment in real auto highlights (1.2.8).
- League item ideas pop-up in a real match ("Item ideas shown: ..."), borderless mode, and that it shows in clips (1.2.9).
- Recording follows the game to a second screen ("Recording the game's screen (DISPLAY2 ...)") (1.2.9).
- 1.3.0 League update: benchmarks box + objective timers in game, panel while dead, match summary card, match
  analysis in My clips, OP.GG ("OP.GG: region ..., rank ...", "OP.GG has the match"). Respawn times assumed: Dragon 5:00,
  Elder/Baron 6:00, inhibitors 5:00.

## Ideas not built yet
Slow-mo on the big moment, end card with K/D/A and verseplatform.gg,
mic noise removal, auto match montage, in-game replay viewer, auto-post drafts to Verse, Clip of the Week on the site,
quieter Discord posts for small fix releases.
Waiting on Riot's production key (app 897128): loading screen info (ranks), skill order / rune ideas. Not doing: augment
pick/win rates (Riot bans augment win rates), enemy ult timers (banned), jungle pathing.
