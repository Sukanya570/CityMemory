@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo Create the environment first using run_windows.bat
  pause
  exit /b 1
)
.venv\Scripts\python.exe tools\etl\import_civic_grievances.py
pause
