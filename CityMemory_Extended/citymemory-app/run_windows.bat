@echo off
cd /d %~dp0
py -m venv .venv
call .venv\Scripts\activate
python -m pip install -r requirements.txt
python server.py
pause
