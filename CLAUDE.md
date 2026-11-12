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
- `verse_desktop.py`: the app. Window (closing to the tray or minimising unloads the page, `App.park`; `show_window` reloads it;
  while a game is on the window shows `ui/paused.html`, `App.pause_for_game`/`resume_after_game`, "Open anyway" = `Api.open_anyway`,
  config `pause_window_in_game` defaults on), tray, `App` (recording control, save queue, death review, watermark queue,
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
- `finals.py`: The Finals highlights. No game data feed, so the recorder adds a "tap" output (rewind_core TAP_W/TAP_CROP:
  a 960x216 grey copy of the banner area under the crosshair, 4 fps, on ffmpeg's stdout) and Windows' built-in OCR
  (pywinrt `winrt-*` packages) reads "ELIMINATED <name>", "TEAM WIPE", "TEAM STOLE A CASHOUT", cashouts. Checked in win_checks.
  Keeps session numbers (incl. $ from banners) for `finals_overlay.py`: elimination card (League-style highlight card, "combo" spot = the Clipped by card's spot, in clips; game icons downloaded from thefinals.wiki to DATA_DIR/finals_icons),
  "your game so far" box (stats box spot), session summary (finals_history.json) and a session folder in My clips.
  Embark/EAC: only the player's own numbers from their own pop-ups, nothing about enemies.
- `wow.py`: World of Warcraft highlights (Forever, Classic, retail) from WoW's combat log file (/combatlog), tailed from
  `<install>\_<flavour>_\Logs\WoWCombatLog*.txt`: boss kills/wipes (ENCOUNTER_END), big pulls (PARTY_KILL of 4+ mobs),
  biggest hit/heal (crit fields read from the line end), PvP killing blows and multis, deaths. Moments that arrive in
  one burst but happened apart get separate clips. Settings key "World of Warcraft"; `rewind_core.FOLDER_GAMES` names
  the flavour from the install folder (WoW: Forever etc). Blizzard's web API can't do live data.
  1.4.2: the app installs a tiny add-on (Interface\AddOns\VersePlatform, LoggingCombat(true) on PLAYER_ENTERING_WORLD)
  into every WoW flavour folder so players never type /combatlog; setting `wow_auto_combatlog`. Forever interface = 16001.
- Highlight switches are per game: `highlights.GAME_EVENTS` + `events_config(cfg, game)`; Settings has one section per game.
- In-game shortcuts are per game: `App.game_shortcuts()` (League: item_ideas/lol_box/overlay_move_hotkey; The Finals:
  finals_box/finals_move_hotkey). Each combo is registered once and acts for the game being played. Overlay spots per game
  via `MoveMode.GAME_ITEMS` (the save pop-up spot is shared, except WoW: `wow_popup`, top middle by default, swapped in by
  `App.overlay_positions`; `App.playing_game` counts every WoW flavour as World of Warcraft; `wow_move_hotkey`).
- `triggers.py`: "clip that" voice command (Windows System.Speech) and controller combos (XInput).
- `lol_live.py`: League companion loop: objective timers strip, the panel while dead (own stats vs `lol_history.json` averages,
  lane item gold, item ideas), match summary card + `summary` on the match. Riot policy: no enemy cooldowns, no win rates.
- `opgg.py`: OP.GG's public MCP server (mcp-api.op.gg/mcp, same as the website's guides): rank, champion at your tier
  (KDA, win rate), top players (CS/gold per min from leaderboard totals), your real game after (gold, damage, lobby rank).
  Answers are a class-text format, `parse()` reads them. Server from League's LeagueClientSettings.yaml. Cached in opgg_cache.json.
  OP.GG has no per-rank CS/gold averages, so farming compares with your usual and with top players.
- `lol_items.py`: League item ideas pop-up (counter items from enemy items on Tab, Data Dragon names/icons; shown while dead or Alt+Shift+I).
  Keep it inside Riot policy: always 2+ choices with reasons, no win rates, only Tab info.
- `overlay.py`: the "Last 60s saved by Verse Platform" pop-up, the League strip window, and `MoveMode` (Alt+Shift+M drag boxes;
  spots saved as screen shares in `overlay_positions`). `watermark.py`: animated "Clipped by Verse Platform" card for the
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
- Pro team Roster tab (published 3 Nov 2026): pro team = UserProfile with is_pro_team. RosterMember, TeamGameSettings
  (server-only edits by the team account or admins). Roles per game in one shared list (Coach/Manager/Analyst staff,
  Content creator section, "Player" for other games). Old UserProfile.team assignments show in a private "Needs sorting" list.
- Events tab order: Verse Brackets, Team Up, Community. Team Up (published 3 Nov 2026) = Tryouts (Tryout +
  TryoutApplication, anyone can post: just me / Verse team / pro team) and one combined Looking for team board (region
  flag pickers everywhere). Untested end to end with real accounts.
- Game icons: one shared icon map in the app's code (clip page, Upload picker, tournaments). Admin-only /IconReview
  page (open it in the editor's Preview, the standalone preview isn't signed in) shows current vs candidate icons;
  the builder has server tools to find candidates (Steam clienticon, App Store artworkUrl512, official site icons,
  Wikimedia logos) and convert to 128px PNG. No light tiles: dark single-colour logos are recoloured white, EA-style
  badges use a knockout (dark to white, white to transparent). Every icon is checked by eye before it goes in the map.
  Images we supply go on the repo's `site-assets` branch (raw.githubusercontent URL). As of 5 Nov 2026 (midday): 619 games with their own icon plus 3 name aliases, 436 on the no-logo list, Retry later empty (its 15 games were taken with their current App Store icons, event art included, on the owner's say so; swap them for plain versions later if wanted). Every game has been tried. Only "Other" (a catch-all tag) is meant to stay on a letter. The App Store (iTunes Search API) works again; mobile games were matched by exact app name, with Google Play and official site icons as fallbacks. App icons are full square art and are kept as is. The review page has "To review", "Retry later" and "All icons" tabs and is kept permanently (owner wants it forever, for future updates); the builder must never add to the map before approval, and must always append to the review queue (it once wiped it by replacing). Name aliases are fine for same-logo games (e.g. Mass Effect Legendary Edition uses Mass Effect, Resident Evil 3 uses RE3 Remake, CoD: Cold War uses Black Ops Cold War). Full colour logos: remove background only, never recolour (recolouring turned Pokémon subtitles into white blobs). Batches must only pick games still showing a letter (check the map and name aliases first).
- WoW: Forever (built 4 Nov 2026, published by W that night): Blizzard API namespaces static-forever-REGION,
  dynamic-forever-REGION, profile-forever-REGION work (not in Blizzard's docs yet). Admin probe function
  blizzardForeverProbe. Battle.net link now asks openid + wow.profile, reads Forever characters once (token never stored),
  WowCharacter refreshed with the app token (once a day when viewed); deleted on unlink or when Blizzard says gone.
  Data store: WowClass/WowSpec/WowTalentTree (940 nodes)/WowItem (lazy)/WowIcon (our own copies; the forever icon
  folder returned 403 on 4 Nov so retail icons are used until it works). Blizzard terms: keep data max 30 days, so a
  scheduled job refreshes anything older than 25 days (locked to admin or scheduler secret). Guides > WoW: Forever
  (public from 4 Nov): class > spec > Talents (real trees), Gear path, Levelling (Draft badges); Build path shows "coming soon" to non-admins until a spec is marked checked.
  Built 4 Nov (not published): 5,916 Forever items (WowItem, class rules from full item docs and item sets, class
  weapon/armor proficiency table, junk filter), WowStatPriority (draft weights, 27 specs), gear path per spec for
  1-10 ... 51-59, 60 Levelling/Dungeons/Raid/PvP (score = stats x weights; dungeon/raid sources empty until Blizzard
  fills journal data), WowBuildPath drafts (talent rules from tree connections + 5 points per row; hidden from
  non-admins until marked checked), WowLevelRoute drafts (Alliance/Horde incl. Skyborne/Zephras Isle, own words),
  admin "Edit guide" panel with history/restore and talent rule checks, personalised "Your characters" (next
  upgrades by score, next talents; refresh reads specializations). Untested with real characters yet.
  Levelling steps show zone icons from each zone's "Explore <zone>" achievement (stored, in the 25-day refresh).
  Icon downloads reject non-images (Blizzard's forever image folder returned error pages on 4 Nov). Game Stats WoW
  card has "Open my guide" per character (owner only); the guide shows a "Link Battle.net" prompt to signed-in users
  without characters.
- WoW: Forever launch day check (5 Nov 2026, not published yet): static-forever data matches what we imported (9 classes, 27 specs, 470 unique talent nodes; our 940 counts class trees once per spec), build 1.60.1_70399. dynamic-forever and profile-forever still 404 (us/eu), so no characters can load yet; the journal is still empty, so Dungeons/Raid gear sources are empty. The Forever icon folder now works: all 1,504 WowIcon copies switched from retail to Forever. Builds and last-modified dates are saved per import and shown on the admin Edit guide panel. Items above level 60 are hidden from gear paths (only the Swami Hat). Zephras Isle zone icon = "Master of Darkspear Islands" achievement icon. New WowForeverStatus + wowForeverWatch: a daily 3:30am Sydney admin-only check of realms/characters/journal; it shows a green banner on the Edit guide panel when any goes live and fills Dungeons/Raid sources once when the journal does (a later loot change needs a manual rerun). Character refreshes are skipped until profile answers.
- To do (6 Nov arvo, with W at his PC): community probes (Blizzard API forum thread 59774, 2 Nov) say
  /profile/user/wow?namespace=profile-forever-{us,eu} works with a user token and dynamic-forever realm index works
  (US/EU/TW; KR 403); static needs the versioned namespace static-1.60.1_70399-forever-{region} (plain static-forever 403);
  realmless /profile/wow/character/{name}-{surname} not routed yet. Our builder got 404 on dynamic-forever-us on 5 Nov,
  so compare our calls (host, token type, namespace) with these, fix, then W logs out of WoW and reconnects Battle.net.
  Armory shows characters from level 10. Then: character on Game Stats + personalised guides.
  W hit level 10 (5 Nov) and the linked account still showed nothing. Note: characters are only read at link time
  (user token not stored), so a reconnect is needed after levelling/logging out; check the link code's call too.
- WoW: Forever characters WORK (6 Nov arvo, published by W up to the realmless fix): account profile
  /profile/user/wow (user token, at link) lists characters with name + surname, NO realm; single character lookups work
  with our APP token at us.api.blizzard.com/profile/wow/character/<slug> (slug = name-surname LOWERCASED, e.g.
  verse-platform; capitals 404), namespace profile-forever-us. All sub paths answer except character-media (404, no
  avatar): equipment, specializations, statistics, professions, pvp-summary, reputations, collections (pets, mounts),
  achievements, quests, titles, appearance, encounters. W = "Verse Platform", Windshaper Skyborne Warrior, Horde, plays Fury.
  Built 6 Nov (preview, W to publish): link callback saves per-region status (forever_read) + admin-only raw log; no wipe on
  errors; Refresh characters button; app token refresh (on view if >12h, nightly), 30 day delete rule; WowCharacterDetail
  per refresh; character page (header, gear, stats, talents, professions, PvP, reputation, collections; no clips section,
  W's call) with Blizzard icons (faction crests inv_bannerpvp_01 Horde / _02 Alliance approved); anonymous talent snapshots
  + admin "Talent picks" tab. Talent rule check now counts class+spec trees together and flags late last-row talents.
  Build paths: Claude is rewriting all 27 specs from the real Forever trees (builder exports compact talent lists per class).
  ALL 27 done 6 Nov with notes (pass the rule check, row 7 talent at 40 each); all marked checked on W's say so 6 Nov
  (visible to users once published). Gear paths (27) and levelling routes (8) also marked checked 6 Nov; Dungeons/Raid
  tabs show "Dungeon and raid loot will appear here once Blizzard shares it." until journal loot exists; icon repair in the
  WoW import tool (194 of 199 item icons, 14 talent icons fixed; junk filter blocks Template/DNT/Test/Placeholder items).
  Next: lock down BattlenetLink reads + the UserProfile email gap. Admin "Data fixes" tab (switchable) patches Blizzard data bugs: BM Intimidation needs only Bestial
  Swiftness; Balance Nature's Majesty needs nothing, Splendor needs Majesty; hidden leftovers: Holy row 8 Holy Specialization,
  MM row 8 Improved Serpent Sting, Survival row 7 duplicate Lightning Reflexes. The two loops need an in-game check.
  Druid has only Balance, Feral Combat, Restoration (no bear spec); Feral build takes Shifting Power 40 + Primal Bite 41.
  Base44 prompt box: a "/word" in the text opens a skill picker and blocks Send, so avoid slashes in builder prompts.
- Privacy (6 Nov, built, W to publish): BattlenetLink/XboxLink/SteamLink now server+admin only, read through one server
  function (owner: link state, tag, WoW settings, sync status; others: only badge bits). WowCharacter/Detail, admin log,
  talent snapshots were already server/admin only. Messages readable only by sender/receiver (+admins), send only as
  yourself; Follow: accepted readable by all, pending only by the two people, create as yourself; Notifications only the
  recipient. 4 old follows with no status set to accepted. Still open: profile emails readable by any signed-in user
  (~55 files use them; plan: add user ids to profiles and messages, server inbox function, move lookups server side, then
  drop the field), notifications can be created for others in your own name (move to server later).
  Stage 2a built 9 Nov (W to publish): profiles have a server-set account id (394 backfilled, 15 orphan profiles with no
  account), messages have sender/receiver account + profile ids (73 backfilled); server functions for inbox/unread,
  conversation, send (also clip/profile shares), and react/edit/delete/accept. Chats poll every 5s (no live updates).
  Published 9 Nov; backfill rerun (0 missing); Message locked to admin/server only (approved 9 Nov, inbox + chat checked
  live as StupendousSmaug afterwards). Push notification chat links now use the username (needs publish). Still on email
  server side: notification, account deletion, migration functions. Next: stage 2b, clips/comments/tags/follows/stats to ids.
  Stage 2b in 4 rounds: 1 profiles+follows+fans, 2 clips/comments/tags (home+discover following feeds too), 3 events/
  tournaments/tryouts/admin pages/achievements follower counts, 4 sign-in + own profile by account id, then emails off profiles.
  Round 1 built 9 Nov (W to publish): server functions for public profiles (email etc stripped), follows (state, counts,
  lists, follow/unfollow/requests, server writes the follow + notification), fans, suggested profiles, blocked list.
  Backfill: 780 follows, 119 fans (1 each points at a deleted account). Re-run the backfill once after publishing (old live
  code writes rows without ids until then). Request badges now refresh every 30s. Following count still counts duplicates
  and deleted accounts (W shows 23, list 20), fix in round 3. Test side effect: kealanclarke unfollowed and refollowed
  (follow date now 9 Nov, a push may have gone out).
  Round 1 published 9 Nov, checked live (StupendousSmaug 7 followers, 9 following); backfill rerun filled 0.
  Round 2 built 9 Nov (W to publish): server functions for home feeds (All/Following/Esports), Discover, profile clips,
  tagged/liked/scheduled, likes, reposts, untag, comments, Creator of the Month, upload (server sets author + tag notices),
  email-free user search for the tag picker; blocked/private hiding now server side; Following tab shows suggestions when
  empty; admin-only skip-notice test switch. Backfill: 916 clips, 2,439 likes, 206 comments, 365 reposts, 8 CotM, 1 saved
  desktop clip; 1 tagged deleted person on 4 clips dropped. Rerun backfill after publish. Not tested: real upload, untag.
  Still email: notifications, polls (voting), achievements/blocks/badges/game stats on profile, contest entries, featured,
  reports, event banner + boost pickers, admin CotM controls, Search user search, @mentions, monthly CotM job.
  Round 2 published 9 Nov (untag, feeds, like checked live; real upload with tag still to try); rerun filled 0.
  Round 3a built 9 Nov (W to publish): profile achievements/blocks/badges/game stats, following counts (real unique
  follows of existing accounts, not self: 14 following + 8 follower counts changed, StupendousSmaug now 6/9), Search +
  @mentions email-free, polls+votes, admin CotM controls + fandom analytics, monthly CotM job saves ids (no email in
  reply or admin mail), Reports shows "Verse user" for missing reporters. Backfill: 647 achievements (6 for 2 deleted
  accounts), 1 block, 2 polls, 2 votes. Round 3b left: events/registrants, banner + boost pickers, Brackets, Verse Teams +
  invites, Tryouts/LFT, roster/pro team, Creator Leagues + contests, featured, verification form, admin Affiliates/
  Featured/Verifications/Reports lookups/dashboard user list. Still email after: notifications, earning achievements,
  own profile edit (round 4), link records (server only, fine), admin email tools (by design).
  Clips black in the Base44 editor preview: preview sends no referrer and Bunny Stream library 611564 had "Block direct
  url file access" on (403). Turned OFF 9 Nov on W's say so; preview plays now. Allowed domains list is empty anyway.
  Round 3a published 9 Nov; rerun filled 0. Speed pass: lookups now run in parallel, search no longer reads the whole
  profile table, follower counts counted server side (Home ~0.45s, Discover 0.52s, Search 0.24s; each server call ~0.16s).
  Round 3b built 9 Nov (W to publish): Brackets/Teams/invites/Tryouts/roster responses email-free, event registrants,
  Creator Leagues (opted-in only), Discover spotlight (no admin notes), verification form server side, banner/boost
  pickers, contest judging by profile id, one admin-only profile service for Dashboard/Verifications/Featured/Reports/
  Affiliates (only place emails show). Backfill: 1/1 featured, 27/29 verification requests.
  ROUND 4 FINDINGS: no read rule (readable even logged out): UserProfile, Video, Comment, Like, Repost, Fan, Block,
  Achievement, VideoPoll, PollVote, CreatorOfMonth, Referral, Affiliate, FeaturedPlacement, VerificationRequest,
  Leaderboard, EmailChangeRequest (lock first). Partly open: Follow (accepted, both emails), Tournament (creator email).
  Creator email stored on most records incl. CommunityEvent, Team, VideoView, WatermarkedVideo, OsrsFundAllocation (open),
  TournamentEntry, Match. Video has an old author name field (one holds "william"). Admin dashboard reads email change
  requests directly with admin access.
  Round 3b published 9 Nov. Round 4 step 1 (9 Nov): EmailChangeRequest + VerificationRequest LOCKED to admins only
  (read/create/change/delete; server unaffected). 2 approved verification requests (SezzRacing, taylor) have no profile.
  Round 4 step 2 built (W to publish): sign-in/layout/own profile by account id (profile created on first sign-in),
  terms screen server side (referral + affiliate auto fan + terms by ids, decline removes profile), edit profile/
  username/photo via server (photo save untested), badges earned server side, browser creates no notifications (one
  shared notify step storing ids), old clip author name cleared on 915 clips (clear again after publish).
  Known bug kept: sign-up order only computed for admins, so every non-admin passes Early Adopter/Verse Pioneer.
  Lock plan after publish: owner|admin: Comment, Like, Repost, Block, Achievement, PollVote, CreatorOfMonth, Follow (own);
  admin only: VideoPoll, WatermarkedVideo, VideoView, OsrsFundAllocation, Fan, Referral, Affiliate, FeaturedPlacement,
  Team; Notification create admin/server only. Not ready: UserProfile (roster rank list, my roster spots, verification
  form + Creator Leagues own profile by email, 5 game stats functions), Video (clip download function), Leaderboard
  (Creator Climb reads directly, rows hold emails). CommunityEvent stays open. Tournaments keep host/test rules.
  Round 4 step 2 published 9 Nov (sign in, bio, photo checked live by W). LOCKS APPLIED 9 Nov: owner|admin read on
  Comment, Like, Repost, Block, Achievement, PollVote (signed-in create, owner|admin change/delete); Follow read only
  your own; CreatorOfMonth own record + admins; admins only: VideoPoll, WatermarkedVideo, OsrsFundAllocation, Fan,
  Referral, Affiliate, FeaturedPlacement, Team, VideoView; Notification create admin only (approved by Claude).
  Checked signed out + live as StupendousSmaug: comments, likes, polls, badges, fans, CotM banner, feed all fine.
  Step 4 built (W to publish): roster lists, verification form, Creator Leagues, 5 game stats functions (profile id or
  own only), clip download, Creator Climb all server side. Next: move feed view counter + share counter to server,
  drop email lookup from public profile function (lets anyone check if an email has an account), 15 profiles with no
  account id, then lock UserProfile (owner|admin read, badge/tier fields admin only), Video (owner|admin), Leaderboard
  (admin). Clip downloads: Bunny refuses the watermarked copy, none made since 31 Oct, needs looking at.
  Counters built 9 Nov (W to publish): feed views + all 3 share buttons via server, 1 view per viewer per clip per 30 min
  (signed out: max 10 per network per clip per 30 min, hashed addresses), comment likes one per account. Admin dashboard
  is server side, unaffected by locks; matches DB (916 clips, 429 sign-ups, 2,440 likes, 207 comments, 365 reposts,
  24,166 views, 220 shares; clip-stored counters drift slightly lower: 2,388 likes, 197 comments). Public profile lookup
  no longer takes emails; old email links work only for admins or people who got a notification from that person.
  The 15 profiles without account ids are all deleted accounts (not deleted, suggest hide or remove).
  FINAL LOCKS 9 Nov (after W published counters): UserProfile read/change owner|admin, create signed-in, delete admin;
  admin-only fields verified, pro player, pro team, fan eligible, team, team logo, brand account, login email, last
  username change. Video read/change/delete owner|admin, counts + monthly views + feed ranking admin only. Leaderboard
  admin only. Game stat ranks stay owner-editable (Game Stats tab saves from browser). Claude checked live as
  StupendousSmaug: raw reads return only own rows (1 profile, 9 clips, own likes/follows), signed out 0 profiles;
  other profiles, CotM badge, counts all show. Builder checked signed out: feeds, clip page, search, Creator Climb, CotM,
  view/share counting all fine, no emails. Pending publish: signed-out viewer recognised by browser not network (was
  double counting), Creator Leagues join moved to server; THEN lock league tier + season score. W to test as normal
  user: change banner, pin a clip, edit a clip title, join Creator Leagues.
  Published 9 Nov (W pinned a clip OK). League tier + season score now admin only (join + nightly jobs server side).
  Signed-out repeat views no longer double count. Final sweep leaks: Tournament creator email (visitors, 4 rows),
  Notification sender email (recipient, 1,673), Follow other party email (780), own clips' tagged emails (133),
  Block blocked email (1); empty but open: ad campaigns, creator leads, partnerships, reports, suggested creators,
  device tokens, teams. Asked builder (9 Nov) to lock the empty tables and blank those email fields after copying
  them to an admin-only backup table, then stop writing them.
  Done 9 Nov (W to publish): empty tables locked (Reports read admin, create own; DeviceToken via server only; ad
  campaigns, creator leads, partnerships, suggested creators, teams admin only. NOTE ads in Home feed will need a server
  read once campaigns exist). 1,982 emails backed up to an admin-only backup table, then blanked: 4 tournament creator
  emails (server-created records still show the platform system address), 1,673 notification sender emails (2,734
  notifications got account links; 146 senders have no profile), 305 tag emails on 133 clips. New records no longer
  store them. Follows (780) + Blocks (1) left: ~25 server places use their emails. TOMORROW: after W publishes, blank
  emails the old live code wrote meanwhile, make Follow + Block admin-only read (browser never reads them), recheck live;
  later move those ~25 server spots to profile ids. Tagged tab only scans newest 200 clips (old limit, misses older tags).
  W published this batch 9 Nov 22:45. Also TOMORROW: Blizzard's WoW: Forever Armory now shows a full 3D character
  render with gear (W's screenshot 9 Nov), so re-probe character-media (was 404, no avatar) and, if it answers, show the
  character picture on our character page and Game Stats card.
  10 Nov: character-media now WORKS (200, us host, profile-forever-us): avatar + avatar-sd (jpg ~3 KB), main-raw +
  main-sd-raw (png ~294 KB, full transparent render) from render.worldofwarcraft.com/forever-us/character/...; no inset
  or main. Built 10 Nov (W loved it): own copies of render + portrait saved with the character refresh; character page
  shows the render between the gear columns on a faction-tinted grid; round portraits with class badge on Game Stats.
  Asked 10 Nov (building): brighter empty gear slots, faint Verse logo in the grid (red Horde, blue Alliance), guide tabs
  "Character Search" (region us/eu/kr/tw + name-surname, public Blizzard data only, agnostic: never looks up or shows
  Verse accounts; the Show my WoW characters switch only affects the Verse profile (W's call), cached ~1h, rate limited) and "Guild Search" (probe Forever guild endpoints first; Armory guild example: beast).
  Built 10 Nov (W to publish): empty slots dashed + brighter, faint faction-coloured Verse logo behind the render;
  Character Search tab (tested Lengthy Lionel, complete); Guild Search tab. Forever guilds: profile namespace only
  (data namespace 404), realmless slug (beast: Horde, 13 members, GM Dexie Bandit), roster works, achievements and
  activity empty, no crest (faction banner used). Portraits for first 50 roster members. Cache 1h (not found 10 min),
  30 searches per 10 min per visitor (signed out: short fingerprint), search pictures load from Blizzard (not stored),
  cache older than 30 days deleted. KR/TW returned not found (not 403) for Verse Platform; untested with real KR/TW chars.
  W checked all of it 10 Nov 7am ("all worked") and is publishing. TONIGHT: privacy (blank emails old code wrote,
  Follow + Block admin-only read, recheck live), then clip downloads, Early Adopter bug, 15 leftover profiles, Tagged tab limit.
  W (10 Nov arvo): tonight also work on the website's Download page (desktop app page) using The Finals clips we made; W
  will share them.
  W (10 Nov): Mobalytics' Fury Warrior talent order (levels 10-60) differs from ours: it goes Cruelty, Lingering Rage,
  Furious Precision, Blood Craze, Enrage, Death Wish at 30, ... Bloodthirst at 40, Flurry, Dual Wield Spec, Deflection,
  Improved Rend, Improved Tactical Mastery, Anger Management, Deep Wounds 59-60. Later: compare with our Fury build path
  against the real Forever tree and rules (don't copy theirs; check each choice and explain differences to W).
  CHECKED 10 Nov: Blizzard live data still build 1.60.1_70399, identical to ours (53 Warrior talents). Mobalytics uses
  original-Classic values: Flurry 5 ranks (Forever max 3), Improved Tactical Mastery 5 (Forever 3), "Raging Blows"
  (doesn't exist in Forever). Our Fury path is valid (rows/points checked by hand): Cruelty, Unbridled Wrath, Enrage,
  DW Spec, Death Wish 30, Furious Precision, Imp Execute, Flurry 35-37, Imp Whirlwind, Bloodthirst 40, Imp Execute,
  Imp Berserker Rage, then Arms Imp Heroic Strike, Imp Rend, Imp Charge, ITM, Deep Wounds, Anger Management, Impale
  (33 Fury / 18 Arms). W's character shows Cruelty 5/5 (level ~15). Offered: note on the build page about other guides,
  and an optional sustain variant (Blood Craze 3 + Gore Drinker 2 instead of Imp Execute + Imp Berserker Rage).
  10 Nov eve: Follow (781) + Block (1) locked to admin-only read, live checks OK (test follow/unfollow on REGXN, notice
  deleted). No new emails written since blanking. CLAUDE'S LIVE CHECK as StupendousSmaug found 2 leaks via the built-in
  created_by field (can't be blanked): Notification (62 of his 86 notices were created by other users in old browser
  code, 24 other emails) and CommunityEvent (open to signed-out visitors, creator email). Asked builder: serve both via
  server functions without created_by, then admin-only read (after publish if needed), and redo the sweep counting
  created_by on every table + team invites. LESSON: always check created_by when sweeping for leaks.
  Fix built 10 Nov (W to publish, THEN lock Notification + CommunityEvent to admin-only read): notifications bell/page/
  mark read via server (no created_by; new ones appear within 30s, not instantly), community event lists via server.
  Redone sweep (created_by): Notifications 2,116 readable by non-creators (closed by the lock). Public tables showing
  ADMIN emails as creator: W's on app settings, map locations, WoW guides/routes, 1 tournament, 4 tournament entries,
  4 talent fixes; James's (st...@gmail) on the 3 desktop release records, readable signed out (Download page reads that
  table, so needs a server function first). Next: serve those via server functions and lock them.
  W published 10 Nov 18:30; Notification + CommunityEvent LOCKED admin-only read. Claude verified as StupendousSmaug:
  raw reads return 0 (signed in and out), notifications page works. Built (W to publish): build paths, routes, talent
  fixes, stat priorities, map locations via server; tournaments refresh every 15s instead of live (live link sent whole
  records); email-free server source for desktop releases. Desktop app never reads Base44 releases (GitHub only).
  FOUND: AppSettings had NO rules (anyone could read AND change, e.g. turn off welcome email); game genres + guide
  cache writable by anyone. Asked builder to lock now: AppSettings admin-only all, DesktopRelease admin read, genres +
  guide cache admin-only writes. After W's next publish: admin read on map locations, build paths, routes, stat
  priorities, talent fixes; tournaments + entries admin read plus host rule.
  DONE 10 Nov: AppSettings admin-only all, game genres + guide cache admin-only writes (reads open), DesktopRelease
  admin-only all (approved by Claude; nothing in repo/CI writes it, Download page reads GitHub). Live tests OK.
  PRIVACY WORK DONE 10 Nov 19:00 (after W's publish): build paths, routes, talent fixes, map locations, stat priorities
  admin-only; tournaments + entries admin read plus host rule (Claude approved MapLocation, WowStatPriority,
  TournamentEntry cards). Claude's final live scan as StupendousSmaug over 52 tables, signed in and out: no other
  person's email anywhere (created_by included). Events/Brackets list loads (Halo Reclaimer Rumble, CS2 Open).
  Team invites fixed 10 Nov 19:00: server returns a fixed safe field list (no created_by, creator id or emails),
  TeamInvite admin-only read (no publish needed, server functions were already live). Tested with a temp Clarkie96 team,
  cleaned up. Left for later: ~25 server spots still key follows/blocks by email (server only, not exposed).
  Download page (10 Nov eve, building): W wants an ascent.gg style hero, the League clip shrinks on scroll into the first
  tile of a "Works with your games" grid (3D tiles from our icon map; auto-highlight games LoL, The Finals, CS2, Dota 2,
  WoW badged), plus a Match analysis section. Assets on site-assets branch, download folder: lol-hero-1080.mp4 /
  lol-hero-720.mp4 (first 14s of W's Double kill clip, no audio, faststart), lol-hero-poster.jpg, match-analysis.png.
  raw.githubusercontent serves mp4 as octet-stream + nosniff, so the builder copies them into Base44 storage.
  Download page round 2 built 10 Nov eve (W to check + publish): Used by back under the buttons; League clip flies
  into the LoL tile by itself once per visit (FLIP transform + blur, big video sits over the grid, no replay); auto
  highlight badges removed; match analysis rebuilt in HTML (sharp). The Finals Double kill clip (site-assets
  download/finals-double-kill-{1080,720}.mp4 + poster, copied to Base44 storage) now in "Automatically detect" and
  "View your clip" mocks. Bottom row alignment fix sent. Riot disclaimer at the bottom: W asked to remove it, Claude
  advised keeping it small in the footer (Riot policy requires it, app 897128 under review); W hasn't decided.
  Download page PUBLISHED by W 10 Nov 20:34: clip starts as wide as the games grid (max 70% screen height) under the
  subtitle, plays ~4s, only shrinks into the LoL tile, once per visit; page never scrolls sideways. Still open: Riot
  disclaimer decision (keep small in footer vs remove).
  11 Nov: phones get one pre-made fly-in video instead (site-assets download/lol-fly-in-mobile.mp4 + poster, 1080x608,
  9s loop, made by Claude from a capture of the live grid), tile grid hidden on phones. Published by W. Next idea (W):
  make the rest of the platform look as professional as the Download page; plan first, nothing built yet.
  Site redesign (11 Nov): W wants drafts before any builder work. Style guide (Design System artifact, private to W):
  https://claude.ai/artifact/E2HTqEm2iJc2nRNmLQ86Ba (Orbitron headings, Space Grotesk text, black ground, Verse blue
  #0DA2E7 one primary per view, game chips with icons, Liquid glass for anything floating over clips). W's calls: likes
  stay on clip cards, show real numbers always (no hiding under 10, no New badge), Events stats box stays (prizes paid).
  First mockup: clip viewer desktop (video + 400px side panel) and phone: https://claude.ai/artifact/NtsD5oVgimY8m1TyopkZkr
  Review found: phone-width columns on desktop, feed info/actions far from the clip, text-only game pills on Discover,
  grey chip scrollbars, headings under the top bar, spinner page loads, crowded 9-item top bar.
  Built 11 Nov (W to publish): PHONE player (<768px, Home feed only; Discover uses same player, not switched yet):
  full-screen clip, glass header icon groups (Search moved up), glass All/Following/Esports pill, bare white rail icons
  (like, comment, Boost coin, share, mute, report; repost stays in the Share sheet), glass creator pill + Follow, thin
  blue progress bar, floating glass nav (Home, Discover, Upload centred, Badges, Profile). Shared glass style in
  src/components/verse/verseGlass.css. DESKTOP player (>=768px, Home only): clip left + side panel (400px >=1280, 320
  below), glass play bar + up/down chevrons, wheel = one clip per flick, arrow keys, Space, M, per-clip links, preload,
  Up next row (thumbnail fallback: black or missing thumbs use a frame ~1s in, else dark card with game icon). Desktop
  top bar = floating glass pill (Home, Discover, Events, Guides, Creator Leagues, More = Badges, My clips, Download app,
  Daily rewards, Discord, About, Patch notes, legal, Requests, Delete account, Admin pages). Pages start ~40px lower.
  Note: Chrome screenshots here are scaled (1568 px frame for a 1920 window), so measure with care.
  Drafts added 11 Nov eve (same canvas, pages): Discover, Profile, Events, Guides (desktop + phone each), awaiting W.
  W: top-left of the desktop bar must be the blue V logo image, never a VERSE wordmark (mockups fixed; builder asked).
  Canvas renamed "Verse redesign drafts" (same link). Pages: Clip player, Discover, Profile, Events, Guides, Creator
  Leagues + Badges, Polish (skeleton loading, empty states, branded 404: /Badges 404s with Base44's white page; real
  badges page is /Achievements, uses emoji tabs). Desktop bar logo fix built (preview). All drafts await W.
  11 Nov night, W said keep going: BUILT IN PREVIEW (not published) steps 3-8: Discover (+ Discover uses new player,
  auto load more, 4 across on tablets), Profile (owner card tools on hover / ... menu on phones, tier ring kept on
  avatar, favourite game badge uses icon map + Upload's game picker in Edit profile), Events (all 3 tabs, art cover or
  full+blur when >20% off shape), Guides, Creator Leagues (tier colours), Badges (game badges keep own art), Polish
  (skeleton loading, top bar + avatar kept between pages, empty states, branded 404, /Badges -> Achievements), Search
  (live dropdown: people, games, clips + new Search page). Menus/dropdowns use solid glass rgba(14,14,17,0.92).
  All checked by Claude in the editor preview. W to test and publish everything together.
  MORNING (12 Nov, W): some badges lack icons (e.g. First Blood); show tagged people's profile pictures where tags
  appear; add creator profile pictures on Up next cards (click opens their profile); Discover game filter: show the
  selected game's logo next to its title above the clips; Browse by game search dropdown: show each game's logo. Desktop top bar: add Badges between Creator Leagues and More (take it out of the More menu).
  ALL 6 BUILT 12 Nov morning (preview, W to publish): 48 non-game badges got their own tier-coloured icons (all
  pictures loaded; they just shared one faint medal), game badges fall back to an icon if art fails; tagged people show
  round pictures in the player, side panel and phone player (feed grid cards never showed tags; the server function now
  also returns tagged people's pictures, live already); Up next cards have creator picture + name (opens profile);
  Discover game title + search list show logos; Badges in the desktop bar. Claude checked badges, bar, Up next and
  Discover in preview; tagged pictures not seen yet (needs a clip with tags).
  Badge art (12 Nov): W supplied the designed art for all 100 badges (BADGES.zip, 1920px jpg). 512px copies on
  site-assets badges/NNN-name.jpg (typos fixed: fortnite, pioneer), copied into Base44 storage; the 48 non-game badges
  now use them (stand-in icons only as fallback); the 52 game badges already had the same art at 1024px, kept. Checked in
  preview. Found: badges show only on the Badges page (not on profiles) and the badge earned pop-up never fires.
  Badge awarding (12 Nov): badges were ONLY awarded when someone opened the Badges page (server tallies then; bell
  notice + push via the notification workflow, 640 sent, push code iOS only). Asked builder: award on the server after
  upload/like/follow/comment/share/repost + a 30 min job, dry run first for the catch-up (one bell notice per person
  with the count, no push). Drafts added 12 Nov (canvas pages "Analytics + Game Stats", "Notifications + Messages",
  "Showcase badge"): W asked for a showcase badge (pick one unlocked badge in Edit profile, shown by your name, tap for
  name/tier/requirement) + unlock pop-up. Drafts generated by /home/claude/canvas/gen/*.py (render.py = local check).
  Badge rules (code): Verse Veteran = account 30+ days; Beta Tester = created 5 Jan-10 Apr 2026; Early Adopter = first
  100 by sign-up order; Verse Pioneer = first 500; Verse OG = first 10 (sign-up order now computed for everyone by account
  creation, deleted accounts not counted; Verse OG rule bug fixed). Fixed dry run: 366 people, 933 badges (Veteran 349,
  Pioneer 261, Beta Tester 58, Early Adopter 53, Likeable 47, First Fan 46, First Blood 40, ...). Wrongly held because of
  the old bug: Early Adopter 99 (of 135 holders), Verse OG 1. Auto awarding built (7 automations + 30 min sweep) behind a
  switch, OFF until the catch-up runs; awaiting W's OK. Phone header pills now same glass as the All/Following pill; info
  menu = grouped bottom sheet (Verse / Get verified / Legal / Delete Account in red, real Discord logo), desktop More
  menu same groups (preview).
  DONE 12 Nov (live, W approved): catch-up awarded 933 badges to 366 people (one bell notice each, no push; 3 missed
  notices sent separately); 100 wrong badges removed quietly (99 Early Adopter, 1 Verse OG) after copying to an
  admin-only backup table; automatic awarding ON. Holders now: Early Adopter 89, Verse Pioneer 396, Verse OG 7.
  Pop-up pass (preview): shared pop-up style (phone sheets, desktop glass dialog) on info/More menu items, events,
  profile, clips, teams/tryouts, rewards (Boost buttons now blue), admin dialogs; pop-ups sit above the phone nav;
  Patch notes + Delete Account open as pop-ups. W approved drafts (showcase badge, Analytics, Game Stats,
  Notifications, Messages): queued for the builder, then Edit profile facelift, then the remaining pop-ups (terms
  acceptance, share sheets, comments sheet, Guides detail pop-ups) and all Guides inner pages. AFTER: Claude does a
  full style review of every page and pop-up on phone and desktop (W asked 12 Nov).
  12 Nov ~9:30: built in preview: showcase badge (server only accepts unlocked badges), badge unlocked pop-up (uses the
  bell's unread check, no own calls), new Edit profile. NOT yet built: B Analytics, C Game Stats, D Notifications +
  Messages, remaining pop-ups + Guides inner pages, desktop chip row arrows/wheel/drag.
  SCALABILITY REVIEW (builder, 12 Nov): Elite plan 50,000 integration credits/month (566.8 used, resets 9 Dec). DB reads
  and writes free (but ~1,000 MB/min shared read limit, 350 reads/min per user); server function call ~1 credit per 100;
  workflow run ~0.11; email/AI/upload ~1 each; own-key APIs (Riot, Blizzard, Bunny, Klaviyo, GIPHY, Apple push) free.
  React Query pauses timers when hidden. Per open tab: 3 top-bar counters every 30s = 360 calls/h; chat 5s = 720/h.
  Badge check read every account on every action (biggest read-limit risk). Scheduled jobs ~2,300 credits/month.
  Estimate: ~10 credits per active user hour now, ~1 after fixes. W approved ALL fixes (asked builder 9:40): one combined
  counter call 60s, badge/like milestone/push inside the saving server call (no per-action automations), sign-up order
  stored on profile, chat 15s only while open, 5-min jobs to 15 with early exit, Pokedex warm-up daily, feed ranking
  reads new likes only, tournament live subscription + 60s fallback, whole-table reads fixed; plus Claude's idea: a
  per-user status record (owner read, server write) for counters and per-conversation last-message time, so polling
  reads free DB rows instead of calling functions.
  COST CHANGES DONE 12 Nov ~9:50 (server live, app parts preview): per-user status record (owner read, server write)
  feeds the top bar every 60s + page change (0 credits), badge pop-up only calls the server when the record says a badge
  is waiting; Notifications/Messages pages reuse it; open chat reads a per-conversation last-changed record; per-action
  automations archived (badge check, like milestone, push now inside the saving server call, only relevant badges);
  sign-up order saved on the status record (429 users); scheduled clips + brackets sweep every 15 min with early exit
  (scheduled clips can go live up to 15 min late); Pokedex warm-up daily 3am Sydney (40 entries a run); feed ranking
  only new likes; tournament live updates + 60s fallback; link lookup, share preview count, search read small sets.
  Estimate now ~0.5-1 credit per active user hour (was ~10), fixed jobs ~900/month (was ~2,300). Next cost lever at
  scale: how often feeds and profiles call the server. Unverified: owner-only read rule on the status record (test as
  another user), live published site still pushing every notification type (asked builder 9:57).
  Safety check done 10:05: every notification now created in one shared server place that sends the push (likes,
  milestones, comments, replies, follows + requests, reposts, tags, messages, boosts, clips going live, badges, CotM);
  bracket + tryout/roster notices NEVER pushed before, now added; WoW Forever ready notice always pushes. Live site
  still works with new server code; badges from live actions OK; new sign-ups get sign-up order + early badges via the
  30 min sweep. Live top bar still polls every 30s (costs) until W publishes. Only after publish: near-free counters,
  badge pop-up, change-only list reloads, cheaper chat checks, new Analytics.
  B Analytics BUILT 10:10 (preview): full width, period switch, 6 tiles, Views/Likes/Followers chart, Views by game,
  Top clips, New followers; real numbers per period from a new server function (All time uses saved clip totals).
  ~10:30 BUILT (preview): C Game Stats, D Notifications (server adds clip thumbnails + follow-back state) + Messages
  (no online dot), shared glass pop-up shell, both share pop-ups converted (3 errors fixed). Left: comments, terms and
  Guide detail pop-ups, Guides inner pages, desktop chip-row arrows (arrows + wheel only, NO click-drag: W 10:35).
  W 10:35: OSRS Game Stats says "failed to fetch player data" on Clarkie96 (RSN Lv99Will), asked builder to fix;
  profile tabs row can be dragged around, should be a plain sideways scroll on phones only (no drag, no bounce).
  ~10:45 DONE (preview unless noted): OSRS fix = Wise Old Man was rate limiting our server (429), official hiscores
  added as backup (server fix, live only after W publishes per builder); profile tabs scroll only when they don't fit,
  active tab slides into view, desktop one fixed row; bounce + whole-row drag off on every sideways row; desktop glass
  arrows + wheel (no drag) on Discover, Events, Badges, notification filters, Game Stats, Guide chip rows; comments
  sheet + sign-up terms gate glass; Guide detail pop-ups glass and above the top bar; Guides inner pages: glass back
  button, Orbitron title + section headings, one dark panel, Verse chips (Valorant underline now blue), skeletons.
  Builder couldn't test swipes on a real phone or the desktop arrows. W 10:49: phone compass menu (Guides, Creator
  Leagues, Creator Climb, Events) still old dropdown with light blue icons; asked builder for a glass bottom sheet like
  the info menu + sweep of every other menu/dropdown.
  ~11:00 menu sweep done (phone sheets: Explore/compass, info, clip ... menu, profile ... menu; every dropdown, sort,
  filter, region, Upload pickers, Discover search, Game Stats picker, OSRS item picker, TFT pop-up glass; light blue
  icons white). W 10:58: iPhone zooms on input focus (Guides search); asked for 16px inputs on phones, pinch zoom kept.
  PREVIEW CAPTURE FREEZE: from ~10:10 Chrome screenshots of the editor preview time out (renderer busy), Dashboard
  view fine, live site fine; W says preview is smooth on his phone. Builder fixed a desktop clip progress bar animating
  60 fps forever + chip-row arrows redrawing on every measure, couldn't reproduce. A fresh tab worked once (11:10),
  then froze again right after tapping the info menu, closing it and tapping the compass on the phone preview.
  11:15 W chose to keep reviewing in fresh tabs; next fresh tab froze straight away on load (Home, phone size, signed
  in as Clarkie96). Review in the editor preview is not workable from Chrome right now.
  CAUSE FOUND 11:25: not the app. example.com in the same Chrome window also only draws ~1.5 frames a second, so
  Chrome on W's PC is throttling the window (screen locked/asleep or window covered/minimised). Screenshots time out
  because no frame is drawn. Fix: W wakes/unlocks the PC and brings the Chrome window to the front.
  WoW characters now public by default (W's call): owner switch "Show my WoW characters on my profile"; signed-out
  visitors allowed server side (unconfirmed until published).

  REVIEW LIST (W 12 Nov 13:36, for when he's home; phone screenshots): pages should keep their top part fixed and
  scroll only the list under it: Discover (search + game chips + sort), Badges (title, tabs/progress), Notifications
  (title + filter chips), and similar pages. WoW guide pages (e.g. Guild Search result "Beast") look pre-facelift: plain
  "Back" text not the glass back button, blue roster icon, red-bordered header card; its bottom nav pill is wider than on
  other pages (nearly edge to edge). Discover cards: the game name strip sits on top of the clip picture.
  REVIEW DONE 12 Nov 16:20 (live, desktop; phone from W's screenshots, Chrome window can't shrink to phone size). Sent
  builder 8 fixes (preview): pinned tops (Discover chips+tabs, Badges chips, Notifications title+chips, Events filters),
  WoW pages facelift + normal page width + same wrapper (fixes wide phone nav), game chip top-left instead of bottom band
  on clip cards, Events banner empty strip, section headings all Orbitron uppercase, badge art 80px desktop 64 phone,
  badge art + V logo on system notices, Home skeleton matches layout. Not checked yet: OSRS on Clarkie96 (Lv99Will).
  BATCH 2 queued 12 Nov 16:30 (preview): every Guides inner page full desktop width (were ~560px), standard Verse
  controls in guides (OSRS red, OW2 orange, Pokemon Champions purple, LoL solid blue chips off brand; keep data colours),
  Pokedex regions get starter sprites, About (standalone, old wordmark, cyan) + Privacy/Terms/Delete titles restyled,
  Daily rewards Boost button blue + neutral tiles, Verse Socials (Instagram verseplatform, X VersePlatform, Discord).
  Both batches DONE in preview 12 Nov ~16:40; Claude checked Verse Socials (desktop menu + phone row), Daily rewards,
  OSRS guide width, ALL GUIDES heading. Sent one more: long guide titles truncate on phones (OLD SCHOOL RU...). W to test + publish.
  16:45 W: Guides page top scrolls away. Claude verified Discover/Badges/Notifications pinned in preview; asked builder
  to pin every page with search/tabs/filters (Guides main + all inner guides, WoW guide, Events tabs, Creator Leagues
  switch, Search, Messages list, profile tabs), compact on phones; plus Verse Brackets notices to show the V logo.
  16:55 queued: Guides heading pinned with search (other main pages too where room). 17:11 queued: Edit profile Country
  box white + sweep of every form for white/default inputs. Then Claude rechecks pinning + forms in preview, W publishes,
  Claude checks live (incl. OSRS on Clarkie96).
  17:25 Claude checked preview (phone): pinned Guides heading+search, OSRS tabs+search, Notifications; Country picker
  dark with flags; V logo notices. Sent last fixes: tablet top bar overlap (search over More/Verse Socials at ~630px),
  narrower nav pill on guide pages, Edit profile button wraps, Guides heading tight under header. Upload details
  screen not viewed (needs a file in the preview iframe); builder's form sweep covered it.
  17:22 queued: OSRS Runecrafting icon missing on Game Stats (Clarkie96) + full tablet pass (768/1024, both ways).
  17:35 checked preview: tablet top bar icons only (clean), Runecraft icon + OSRS loads for Lv99Will, profile tabs pin.
  Queued: showcase badge without border box (W), tablet profile header (name squashed to "C", chips overlap).
  17:50 checked preview (tablet, signed in as Clarkie96): profile buttons on their own row under the name (beside it only
  from 1280 wide), showcase badge without its box, top bar says "Verse Socials" in words at tablet width. W to publish.
  18:10 built + checked (preview): no box/border on badge art in the showcase pop-up and badge unlocked pop-up (faint
  dark square is the jpg art itself, W fine with it); profile tabs centred when they fit, scroll from the left when not. W to publish.
  18:15 name row (preview): username, blue tick, pro mark (logo / purple pro team / gold pro player), then showcase badge
  last at name height (32 desktop, 28 phone), 14px gap before it. Clarkie96 verified was on briefly to preview the combo, turned
  OFF again 18:20 (only change). W publishing this batch 18:20; Claude to check live after (incl. OSRS on Clarkie96).
  1.5.0 desktop build succeeded 12 Nov 16:17 (run 43160092428).
  SOCIALS (W 12 Nov 13:47): "Verse Socials" item, same words as the menu heading and phone row (W: "Follow" alone is unclear) in the desktop top bar between Badges and More (opens a small glass menu
  with each platform's logo + handle), and a "Follow Verse" row of round logo icons at the top of the phone info sheet.
  Draft on the canvas first; W to send the handles. Optional later: About page "Find us" + footer on end-of-page pages.

  DESKTOP APP FACELIFT (12 Nov, W asked): app UI still used old cyan #06b6d4 + system font. Drafts on the canvas page
  "Desktop app" (AppClips, AppPlayer, AppSettings, AppSmall; generated by /home/claude/canvas/gen/pages5.py, stills from
  site-assets download clips): rail with V logo, recording deck (game icon + red dot, footage bars, keycap, blue Save),
  game chips with icons, match card stat tiles, clip viewer as glass dialog with filmstrip trim, Settings with a jump list
  per game (game icons), Orbitron section titles, blue toggles, white segmented pills, glass select bar/toasts, paused
  screen, What's new, delete check; in-game save pop-up only recoloured (same size/spot), Clipped by card unchanged.
  W said go (12 Nov 12:24). BUILT in main, held for 1.5.0 (NEXT_RELEASE.md): ui/fonts (Orbitron + Space Grotesk
  variable TTF, OFL; media server serves .ttf), new tokens + facelift layer at the end of ui/styles.css, deck game icon
  (get_state "game"), clip badges in .ups row, Settings jump list (.set-nav, one column, fixed section order), filmstrip
  behind the trim bar (library.strip_path, media kind "strip", 10 keyframes tiled, made on first open, deleted with the
  clip), paused.html restyle + game icon, Verse dock + What's new pop-up recoloured, in-game accents (overlay SIGNAL,
  watermark/finals CYAN, squad, lol_live) now Verse blue (13,162,231). Kept native video controls (no custom play bar).
  Checked with a mocked API in local Chromium (/tmp/uitest/run.py). RELEASED as 1.5.0 on 12 Nov (W: "lets just release").

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
The "Ready." line shows encoder, capture method and "(GPU only)". Useful lines: "Resource use ..." (every 5 min: app / recorder / window MB and CPU), "Capture froze", "Switching from",
"Sound output changed", "Saved with no audio", "Told the squad".

## Still to confirm on a real PC (as of 1.4.2)
- 1.4.2: the Verse WoW add-on installs and loads (chat "Verse Platform: combat log on").
- 1.4.1 WoW highlights: a real boss kill, big pull and PvP kill (combat log format, own flag 0x511 and crits already checked with W's logs).
- 1.4.0: confirmed 5 Nov (pause, back to the same page, Open anyway); minimising unloading the page still to check.
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
- 1.3.1 icons: objective icons + dragon element on the timers, lane opponent picture, champion/rank pictures, game logos.
- 1.3.2: the stats and item ideas shortcut set in Settings (`item_ideas_hotkey`).
- 1.3.4/1.3.5: dragging overlays in move mode (Alt+Shift+M) in a real game, more than once per run (1.3.4 crashed on reuse), hide box (Alt+Shift+B), new chart and closed analysis.
- 1.3.6 The Finals: highlights in real matches ("Reading The Finals's on-screen pop-ups", "The Finals: elimination",
  "The Finals banner not understood: ..." for unknown cashout wording), 1080p/1440p, elimination pop-ups in clips, box and
  session summary, game icons downloading. Per-game highlight switches. Save pop-up showing in the next clip.
- 1.3.8: The Finals elimination card (League-style highlight card, top left where Clipped by sits; auto clips marked live_card skip the burned card).
- 1.3.9: League FPS steadier with the stats box; window reopens on the right page after the tray; "Resource use" log lines.
- 1.3.7: per-game shortcuts (The Finals' keys only act in The Finals, League's in League) and per-game overlay spots.

## Ideas not built yet
Slow-mo on the big moment, end card with K/D/A and verseplatform.gg,
mic noise removal, auto match montage, in-game replay viewer, auto-post drafts to Verse, Clip of the Week on the site,
quieter Discord posts for small fix releases.
WoW (W, 6 Nov): character card on Game Stats (Verse style, not a copy of Blizzard's Armory), level-up/quest highlights via
the chat log (need a WoWChatLog.txt sample), quest helper add-on fed by our levelling routes, and later dungeon data:
Blizzard journal (loot, bosses; still empty) + the player's own runs from the combat log (ENCOUNTER_START/END: clear
time, bosses, deaths, wipes) shown on Game Stats and the guides.
Guilds on Verse (W, 6 Nov, later): likely built on Verse Teams (a team type "WoW guild"), linked to the real guild via
Blizzard's guild endpoints once Forever's guild data works (check realmless naming), members confirmed through their own
linked characters, a guild page with members' clips (boss kills first), and recruiting through Team Up / Tryouts.
Waiting on Riot's production key (app 897128): loading screen info (ranks), skill order / rune ideas. On the website, swap the red "R" placeholder
for the real Riot logo on linked account badges (Tryouts) when Riot linking goes live. Not doing: augment
pick/win rates (Riot bans augment win rates), enemy ult timers (banned), jungle pathing.
