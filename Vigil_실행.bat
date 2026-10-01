@echo off
rem Vigil launcher - live instrument monitor. Double-click or use the desktop shortcut.
rem No fixed watch folder: Vigil asks which raw folder to monitor every time it starts
rem (the picker opens at the last chosen folder). A folder given as the first argument skips the picker.
rem pythonw = dashboard only, no console. Cursors and status log go to the state folder.
rem ASCII only on purpose: cmd misreads UTF-8 text on some code pages.
cd /d "%~dp0"
if not "%~1"=="" (
  start "" ".venv\Scripts\pythonw.exe" vigil\run_vigil.py --dir "%~1"
) else (
  start "" ".venv\Scripts\pythonw.exe" vigil\run_vigil.py
)
