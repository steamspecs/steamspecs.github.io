@echo off
setlocal
cd /d "%~dp0\..\.."
python tools\python\build_component_catalogs.py --refresh-imports
if errorlevel 1 goto :end
python tools\python\build_steam_data.py --refresh --concurrency 2 --request-delay-ms 250
:end
pause
