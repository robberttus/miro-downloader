@echo off
chcp 65001 >nul
title Miro Bord Offline Downloader
cd /d "%~dp0"

python miro_downloader.py %*

echo.
pause
