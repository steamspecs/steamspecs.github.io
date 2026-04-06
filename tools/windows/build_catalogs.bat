@echo off
setlocal
cd /d "%~dp0\..\.."
python tools\python\build_component_catalogs.py
pause
