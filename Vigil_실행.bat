@echo off
rem Vigil launcher - live instrument monitor. Double-click or use the desktop shortcut.
rem Set WATCH to this PC's raw folder (a folder given as the first argument overrides it).
rem pythonw = dashboard only, no console. Cursors and status log go to vigil_state.
rem ASCII only on purpose: cmd misreads UTF-8 text on some code pages.
cd /d "%~dp0"
set "WATCH=E:\Yeosu_2026\CAESAR_Hot"
if not "%~1"=="" set "WATCH=%~1"
if not exist "%WATCH%\" (
  echo [Vigil] watch folder not found: %WATCH%
  echo         Edit the WATCH line in this .bat file to this PC's raw folder.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" vigil\run_vigil.py --dir "%WATCH%"
