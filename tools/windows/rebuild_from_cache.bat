@echo off
setlocal
cd /d "%~dp0\..\.."
python tools\python\build_steam_data.py --only-build
pause
