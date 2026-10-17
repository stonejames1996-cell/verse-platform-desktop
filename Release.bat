@echo off
title Verse Platform - Release a new version
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0release.ps1"
echo.
pause
