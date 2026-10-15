@echo off
py -3 "%~dp0scripts\safe_update.py" --launch
if errorlevel 1 pause
