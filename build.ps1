# Builds "Verse Platform Setup x.y.z.exe": a normal Windows installer with Python and FFmpeg baked in.
# Run it with "Build Installer.bat" (double click). Needs internet the first time.
param([switch]$CI)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes downloads much faster
Set-Location $PSScriptRoot

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Find-Python {
    # returns something like "py -3.12" or "python"
    foreach ($c in "py -3.12", "py -3", "python") {
        $parts = $c.Split(" "); $exe = $parts[0]; $rest = @($parts | Select-Object -Skip 1)
        try {
            $v = & $exe @rest -c "import sys; print(sys.version_info >= (3, 9))" 2>$null
            if ($v -eq "True") { return $c }
        } catch {}
    }
    return $null
}

$version = (Select-String -Path rewind_core.py -Pattern 'APP_VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building Verse Platform $version" -ForegroundColor Green

# 1. Python (only needed to BUILD, the finished app has its own copy inside)
Step "Checking for Python"
$py = Find-Python
if (-not $py) {
    Write-Host "Python not found, installing Python 3.12 with winget..."
    winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    Refresh-Path
    $py = Find-Python
    if (-not $py) { throw "Python installed but not found yet. Close this window and run Build Installer.bat again." }
}
Write-Host "Using: $py"

# 2. Build environment
Step "Installing build packages"
if (-not (Test-Path .buildenv)) {
    $parts = $py.Split(" "); $exe = $parts[0]; $rest = @($parts | Select-Object -Skip 1)
    & $exe @rest -m venv .buildenv
}
$vpy = ".buildenv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 3. FFmpeg (gets bundled inside the app)
Step "Getting FFmpeg"
New-Item -ItemType Directory -Force build_deps | Out-Null
if (-not (Test-Path build_deps\ffmpeg.exe)) {
    $zip = "build_deps\ffmpeg.zip"
    Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath build_deps\ffmpeg_x -Force
    Copy-Item (Get-ChildItem build_deps\ffmpeg_x -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName build_deps\ffmpeg.exe
    Remove-Item $zip, build_deps\ffmpeg_x -Recurse -Force
}
& build_deps\ffmpeg.exe -hide_banner -version | Select-Object -First 1

# 4. Freeze the app (Python + all packages + FFmpeg + logo -> dist\Verse Platform\)
Step "Building Verse Platform.exe"
Remove-Item build, dist -Recurse -Force -ErrorAction SilentlyContinue
& $vpy -m PyInstaller --noconfirm --clean verse_platform.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
if (-not (Test-Path "dist\Verse Platform\Verse Platform.exe")) { throw "Verse Platform.exe was not created" }

# 5. Inno Setup (makes the installer)
Step "Finding Inno Setup"
function Find-ISCC {
    foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) { if (Test-Path $p) { return $p } }
    $c = Get-Command iscc -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}
$iscc = Find-ISCC
if (-not $iscc) {
    if ($CI) { choco install innosetup -y --no-progress | Out-Null }
    else { winget install -e --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements }
    $iscc = Find-ISCC
    if (-not $iscc) { throw "Inno Setup didn't install. Get it from jrsoftware.org/isdl.php and run this again." }
}

Step "Building the installer"
& $iscc "/DAppVersion=$version" installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$out = Get-ChildItem Output\*.exe | Sort-Object LastWriteTime | Select-Object -Last 1
$mb = [math]::Round($out.Length / 1MB, 1)
Write-Host "`nDONE! Your installer is ready:" -ForegroundColor Green
Write-Host "  $($out.FullName)  ($mb MB)" -ForegroundColor Green
if (-not $CI) { explorer.exe /select,"$($out.FullName)" }
