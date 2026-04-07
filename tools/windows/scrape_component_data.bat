@echo off
setlocal
cd /d "%~dp0\..\.."

python tools\python\build_component_catalogs.py --refresh-imports %*
if errorlevel 1 (
  pause
  exit /b %errorlevel%
)

pause
