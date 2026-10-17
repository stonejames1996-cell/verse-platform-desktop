# Verse Platform for Windows

The Verse desktop app. The window **is** [verseplatform.gg](https://verseplatform.gg), with the feed, profiles, messages, game tags and the Upload screen always live. On top of that it adds what a website can't do:

**Play → Capture → Save locally → Preview / trim → Publish to Verse**

* **Capture:** notices when you start a game and records in the background. Press **Alt+F10** to save the last 60 seconds (or however long you choose).
* **Save locally:** clips are saved on your PC only (`Videos\Verse Platform\<game>`). Nothing is uploaded unless you publish it, so Verse's storage only holds clips people actually post.
* **Preview / trim:** **My clips** shows every clip with a player. Drag the handles to pick the part to post (60 seconds max).
* **Publish to Verse:** opens Verse's own Upload screen with the clip already loaded and the game picked. Add your caption and hashtags, then post as normal. It goes through Verse's usual video upload, like any other post.

People who install it get `Verse Platform Setup 1.0.2.exe`. Python, FFmpeg and everything else are inside it.

> **One website change is needed** so Verse's Upload screen accepts clips from the app. See [`base44/SETUP.md`](base44/SETUP.md).

---

## Releasing a new version (one click)

Double click **Release.bat**. It asks for the version number (press Enter for the next one), opens `release-notes\<version>.md` in Notepad for you to write what changed, then sends it all to GitHub.

GitHub builds the installer and publishes it as a Release (about 10 minutes, watch it under **Actions**). Then:

* **Everyone's app updates itself.** It checks GitHub every 6 hours, downloads the update quietly, and installs it when nobody's playing (or straight away via **Update now** in the tray or My clips). Settings and clips are kept.
* **The website's Download button** links to `https://github.com/<owner>/<repo>/releases/latest/download/VersePlatformSetup.exe`, which always serves the newest version. Nothing to upload to Base44.

**First time only:** make an empty **public** repository on github.com, run Release.bat and paste the repository address when it asks. It installs Git if needed and opens a browser to sign in to GitHub once.

**Test build without releasing:** double click **Build Installer.bat** to build `Output\Verse Platform Setup x.y.z.exe` on your PC. Any push to `main` also builds a test installer under GitHub Actions.

## Using it

| Action | How |
|---|---|
| Save a clip | **Alt+F10** while playing |
| See your clips | The **CLIPS** tab on the left edge of Verse, or **My clips** in the menu, or the tray icon |
| Post a clip | Open it, drag the handles to pick the part, then **Publish to Verse** |
| Back to the feed | The Verse logo or home icon in My clips |
| Settings | The gear icon in My clips (shortcut, clip length, quality, games, mic, start with Windows) |
| Quit completely | Right click the tray icon, then Quit |

Closing the window keeps recording in the tray.

## Game detection

* Popular games are detected by their program name: League of Legends, VALORANT, CS2, Fortnite, Apex, Overwatch 2, Rocket League, Minecraft, OSRS (RuneLite) and more.
* **League of Legends:** the lobby is ignored. Recording starts when the match window opens and covers the loading screen too. TFT and Arena work the same way.
* When a game closes, recording carries on for 20 seconds, then stops. The footage is kept, so Alt+F10 still saves the ending.
* Any fullscreen app counts as a game too (browsers, video players and launchers excluded).
* Missing a game? Open it, then go to Settings, Games, **Add a game**.

## How the handover to Verse works

1. **Publish** makes a trimmed copy. It's instant when cut on a keyframe, otherwise a quick re-encode on the GPU.
2. The window opens `verseplatform.gg/Upload?desktopClip=<id>`.
3. Verse's Upload page asks the app for the clip (`window.pywebview.api.get_clip`) and gets a private link to the file on `127.0.0.1`.
4. It loads the file into its normal upload flow. You add a caption and hashtags and post, and it uploads to Verse's video host as usual.
5. Verse tells the app it's posted (`clip_published`), and the clip shows **Posted** in My clips.

Only verseplatform.gg can read clips from the PC, and only through a secret link that changes every launch. Other websites get nothing.

## Settings file

Everything is in the Settings page. The rarely needed extras are in `%APPDATA%\Verse Platform\config.json` (quit the app first): `bitrate`, `output_height`, `monitor`, `encoder`, `audio_offset_ms`, `stop_delay_seconds`, `custom_games`, `ignored_apps`, `max_post_seconds` (default 60) and `verse_url` (blank means verseplatform.gg).

## Heads up

* **"Windows protected your PC":** new apps without a code signing certificate show this the first time. Click **More info**, then **Run anyway**.
* **Black clips:** the game is in exclusive fullscreen. Use borderless windowed.
* **Hotkey doesn't work in one game:** that game runs as admin, so run Verse Platform as admin too.
* **Anti-cheat:** it uses the same official Windows capture APIs as OBS and never touches game memory.
* **Log file:** `%APPDATA%\Verse Platform\verse_platform.log`

## Project files

| File | What it is |
|---|---|
| `verse_desktop.py` | The app: window (Verse + My clips), tray, the bridge Verse talks to |
| `rewind_core.py` | Recording, game detection and settings |
| `library.py` | Clip list, thumbnails, trimming for posts, and the local server clips are played and handed over from |
| `ui/` | My clips and Settings screens |
| `base44/SETUP.md` | The change Verse's website needs |
| `updater.py` | Auto update from GitHub Releases |
| `Release.bat`, `release.ps1`, `release-notes/` | One click release, and the patch notes for every version (shown on GitHub, the website and in the app) |
| `Build Installer.bat`, `build.ps1`, `verse_platform.spec`, `installer.iss` | Building the installer |
| `.github/workflows/build.yml` | Lets GitHub build the installer |
