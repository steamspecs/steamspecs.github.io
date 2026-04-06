@echo off
setlocal
cd /d "%~dp0\..\.."
python tools\python\build_steam_data.py --limit 100 --concurrency 2
pause
