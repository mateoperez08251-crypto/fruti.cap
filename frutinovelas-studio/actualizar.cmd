@echo off
py -3 "%~dp0scripts\safe_update.py"
if errorlevel 1 pause
