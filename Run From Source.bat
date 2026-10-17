@echo off
rem For development: runs verse_desktop.py directly without building the installer.
cd /d "%~dp0"
if not exist .buildenv (
  echo Run "Build Installer.bat" once first to set things up.
  pause
  exit /b
)
if not exist ffmpeg.exe if exist build_deps\ffmpeg.exe copy build_deps\ffmpeg.exe ffmpeg.exe >nul
.buildenv\Scripts\python.exe verse_desktop.py
pause
