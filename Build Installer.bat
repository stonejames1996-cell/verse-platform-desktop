@echo off
title Verse Platform - Build Installer
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
echo.
pause
