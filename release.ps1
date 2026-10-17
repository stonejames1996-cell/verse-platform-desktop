# Releases a new version of Verse Platform. Run it with "Release.bat" (double click).
#
# What it does:
#   1. Asks for the new version number (just press Enter for the next one).
#   2. Opens RELEASE_NOTES.md in Notepad so you can write what changed. Save and close it.
#   3. Updates APP_VERSION, saves everything to GitHub and tags the release.
# GitHub then builds the installer and publishes it (about 10 minutes). Everyone's app
# updates itself, and the website's Download button gives out the new version. Nothing to upload.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Git { & git @args; if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') failed" } }

# --- Git ----------------------------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Step "Installing Git (one time only)"
    winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git installed but not found yet. Close this window and run Release.bat again." }
}

# --- First time: connect this folder to the GitHub repository -----------------------
if (-not (Test-Path .git)) {
    Step "First time setup"
    Write-Host "Make an empty PUBLIC repository on github.com first (for example verse-platform-desktop),"
    Write-Host "then paste its address here, like https://github.com/yourname/verse-platform-desktop"
    $url = (Read-Host "GitHub repository address").Trim().TrimEnd("/")
    if ($url -notmatch "github\.com[/:]([^/]+)/([^/.]+)") { throw "That doesn't look like a GitHub repository address." }
    Git init -b main
    Git remote add origin "https://github.com/$($Matches[1])/$($Matches[2]).git"
    # if the repository already has releases, pick up its history and keep the files in this folder
    git fetch origin main --tags --quiet 2>$null
    if ($LASTEXITCODE -eq 0) { Git reset --mixed origin/main --quiet }
}
if (-not (git config user.name)) { Git config user.name (Read-Host "Your name (shown on GitHub commits)") }
if (-not (git config user.email)) { Git config user.email (Read-Host "Your GitHub email") }

$remote = git remote get-url origin
if ($remote -notmatch "github\.com[/:]([^/]+)/([^/.]+)") { throw "The 'origin' remote isn't a GitHub repository: $remote" }
$repo = "$($Matches[1])/$($Matches[2])"

# --- Point auto update at this repository ------------------------------------------------
$core = Get-Content rewind_core.py -Raw
if ($core -notmatch "UPDATE_REPO = `"$([regex]::Escape($repo))`"") {
    $core = $core -replace 'UPDATE_REPO = ".*"', "UPDATE_REPO = `"$repo`""
}

# --- Version ------------------------------------------------------------------------
$current = ([regex]::Match($core, 'APP_VERSION = "(.+?)"')).Groups[1].Value
$p = $current.Split("."); $next = "$($p[0]).$($p[1]).$([int]$p[2] + 1)"
git fetch --tags --quiet 2>$null
$tags = @(git tag --list "v*" 2>$null)
if ($tags -notcontains "v$current") { $next = $current }   # this version hasn't been released yet
Write-Host "`nCurrent version: $current" -ForegroundColor Green
$version = (Read-Host "New version [$next]").Trim()
if (-not $version) { $version = $next }
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Use a version like 1.0.2" }
if ($tags -contains "v$version") { throw "v$version has already been released. Pick a higher number." }

# --- Release notes ------------------------------------------------------------------------
Step "Write the release notes in Notepad, then save and close it"
Start-Process notepad.exe RELEASE_NOTES.md -Wait

$core = $core -replace 'APP_VERSION = ".*?"', "APP_VERSION = `"$version`""
Set-Content rewind_core.py $core -NoNewline -Encoding utf8

# --- Send to GitHub ---------------------------------------------------------------------
Step "Sending v$version to GitHub (a browser window may ask you to sign in the first time)"
Git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { Git commit -m "Release v$version" --quiet }
Git push -u origin main   # GitHub sees the new version number and publishes the release

$actions = "https://github.com/$repo/actions"
Write-Host "`nDONE! GitHub is building v$version now (about 10 minutes)." -ForegroundColor Green
Write-Host "Watch it here: $actions"
Write-Host "When it's green, everyone's app updates itself and the website download is the new version."
Start-Process $actions
