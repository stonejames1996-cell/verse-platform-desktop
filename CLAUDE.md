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
- `overlay.py`: the "Last 60s saved by Verse Platform" pop-up. `watermark.py`: "Clipped by Verse Platform" for the first 2s (always on).
- `updater.py`: auto update from GitHub Releases (`VersePlatformSetup.exe`, sha256 checked, silent install, relaunch).
- `whatsnew.py` + `release-notes/*.md`: the in-app What's new pop-up.
- `ui/`: the My clips / Settings screens (plain HTML/JS/CSS).
- `base44/SETUP.md`: notes on the website side.

## Releases (fully automatic)
1. Bump `APP_VERSION` in `rewind_core.py`.
2. Add `release-notes/<version>.md` (plain bullets, user friendly).
3. Commit and push to `main`.
GitHub Actions (`.github/workflows/build.yml`) builds the installer, creates release `v<version>`, posts the notes to
Discord, and every user's app updates itself within ~2 hours. A push without a version bump builds nothing.
Repo secrets used: `DISCORD_WEBHOOK_URL`, optional `DISCORD_PING_ROLE_ID`, `SQUAD_RELAY_SECRET`.
`Release.bat` / `release.ps1` do the same from a Windows PC.

## Debugging
Ask for `%APPDATA%\Verse Platform\verse_platform.log` (and `crash.log` if there is one) plus a broken clip.
The "Ready." line shows encoder, capture method and "(GPU only)". Useful lines: "Capture froze", "Switching from",
"Sound output changed", "Saved with no audio", "Told the squad".

## Still to confirm on a real PC (as of 1.2.5)
- GPU-only recording ("(GPU only)" in the log, lower FFmpeg CPU in Task Manager).
- Default sound device following ("Sound output changed, recording follows it").
- Squad POV end to end between two PCs (needs the Base44 squadRelay function published; the upload size limit is untested).
- CS2 and Dota 2 highlights in real matches.
- Mobile app iris launch intro on a real phone (lives in Base44).

## Ideas not built yet
Match summary pop-up after a game, slow-mo on the big moment, end card with K/D/A and verseplatform.gg,
mic noise removal, auto match montage, in-game replay viewer, auto-post drafts to Verse, Clip of the Week on the site,
quieter Discord posts for small fix releases.
