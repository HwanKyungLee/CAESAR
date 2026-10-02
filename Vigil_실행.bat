@echo off
rem Vigil launcher - live instrument monitor. Double-click or use the desktop shortcut.
rem
rem   (no argument)         opens PAUSED: choose the raw folder with "Choose folder..."
rem                         (it opens at the last chosen folder), then press Start.
rem   (folder as argument)  unattended: watches that folder and STARTS MONITORING AT ONCE
rem                         (--autostart). Use this form for auto-run after a reboot:
rem                         Win+R, shell:startup, add a shortcut to this file with the folder
rem                         as its argument. Without it a reboot leaves Vigil paused forever.
rem
rem pythonw = dashboard only, no console. Cursors and status log go to the state folder.
rem ASCII only on purpose: cmd misreads UTF-8 text on some code pages.
cd /d "%~dp0"
if not "%~1"=="" (
  start "" ".venv\Scripts\pythonw.exe" vigil\run_vigil.py --dir "%~1" --autostart
) else (
  start "" ".venv\Scripts\pythonw.exe" vigil\run_vigil.py
)
