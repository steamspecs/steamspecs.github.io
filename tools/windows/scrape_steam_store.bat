@echo off
setlocal
cd /d "%~dp0\..\.."

python tools\python\build_steam_data.py %*
if errorlevel 1 (
  pause
  exit /b %errorlevel%
)

pause
