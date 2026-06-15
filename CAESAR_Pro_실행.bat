@echo off
rem CAESAR Pro 실행 — VS Code 없이 더블클릭으로 실행.
rem pythonw = 콘솔창 없이 GUI만. 크래시 로그는 logs\crash.log 에 남음.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" main.py
