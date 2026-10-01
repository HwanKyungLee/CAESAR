@echo off
rem Vigil launcher - live instrument monitor. Double-click or use the desktop shortcut.
rem No fixed watch folder: choose the raw folder with the "Choose folder..." button on the dashboard
rem (it opens at the last chosen folder). A folder given as the first argument is used directly
rem (unattended runs; add --autostart in the command line to start reading at once).
rem pythonw = dashboard only, no console. Cursors and status log go to the state folder.
rem ASCII only on purpose: cmd misreads UTF-8 text on some code pages.
cd /d "%~dp0"
if not "%~1"=="" (
  start "" ".venv\Scripts\pythonw.exe" vigil\run_vigil.py --dir "%~1"
) else (
  start "" ".venv\Scripts\pythonw.exe" vigil\run_vigil.py
)
