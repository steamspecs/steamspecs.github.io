@echo off
setlocal
cd /d "%~dp0\..\.."
if exist ".cache\steam" (
  powershell -NoProfile -Command "Remove-Item -LiteralPath '.cache\steam' -Recurse -Force -ErrorAction SilentlyContinue"
)
python tools\python\build_component_catalogs.py
python tools\python\build_steam_data.py --refresh %*
pause
