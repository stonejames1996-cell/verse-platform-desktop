# Website change for Verse Platform for Windows

The desktop app shows verseplatform.gg in its window. For **Publish to Verse** to work, Verse's Upload screen needs to accept a clip that the app hands over. That's one prompt to the Base44 AI (below), then **Publish**.

Clips are never stored in Base44 by the app. A clip only goes online when the player posts it through the normal Upload screen, which sends it to Verse's usual video host.

## The prompt

> Verse now has a Windows desktop app ("Verse Platform for Windows"). Its window shows this website (verseplatform.gg) and it records gameplay in the background. Clips are saved on the user's PC only. When a user picks a clip in the desktop app and clicks "Publish to Verse", the app opens /Upload?desktopClip=&lt;clipId&gt; in its window. Please make the Upload page support that. Normal web and mobile users must see NO change.
>
> 1. Detecting the desktop app: the app adds `window.pywebview.api` to every page. It can appear a moment after the page loads, so check for it and also listen for the window event `pywebviewready`. `isDesktop = !!(window.pywebview && window.pywebview.api)`.
> 2. Upload page with `?desktopClip=<id>` inside the desktop app:
>    - Show a loading state: "Loading your clip from this PC..."
>    - `const info = await window.pywebview.api.get_clip(id)`. It returns `{ id, url, file_name, mime_type, size, duration_seconds, title, game, recorded_at, thumbnail_url }` or `{ error }`.
>    - `const blob = await (await fetch(info.url)).blob(); const file = new File([blob], info.file_name, { type: info.mime_type || "video/mp4" });`
>    - Feed that File into exactly the same code path as the normal file picker, so the trimmer, cover picker, caption, hashtags, user tags, game picker, validations and the video upload all work unchanged.
>    - Pre-select the game when `info.game` matches one of our games (case-insensitive). Never post automatically.
>    - After the post is created, call `window.pywebview.api.clip_published(id, <URL of the new post>)`.
>    - If anything fails, show "Couldn't load the clip from your PC. Pick it with Select video instead." and the normal file picker.
> 3. Desktop-only buttons (only when isDesktop): a "From my PC clips" button on the Upload screen, and a "My clips" item in the main navigation with `id="verse-desktop-nav"`, both calling `window.pywebview.api.open_library()`.
>
> Don't change any backend functions, entities, other pages, or the upload flow for non-desktop users.

## What the app provides to the page

| Call | Returns |
|---|---|
| `window.pywebview.api.desktop_info()` | `{ app, version, platform, hotkey, capturing }` |
| `window.pywebview.api.get_clip(id)` | Clip details plus a private `url` the page can fetch the video from (only verseplatform.gg is allowed to) |
| `window.pywebview.api.clip_published(id, url)` | Marks the clip as posted in the app |
| `window.pywebview.api.open_library()` | Opens My clips |
| `window.pywebview.api.save_clip()` | Saves a clip now (same as the hotkey) |

## Clean-up from the earlier version

The earlier "Verse Rewind" setup added the tables `Clip`, `DesktopDevice` and `DesktopLink`, the functions `desktopLinkStart`, `desktopLinkPoll`, `desktopLinkApprove`, `desktopMe`, `desktopLogout` and `desktopUploadClip`, and the page `LinkDesktop`. The new app doesn't use any of them, so they can be deleted (ask the Base44 AI to remove them). Delete the one test clip in the `Clip` table first.
