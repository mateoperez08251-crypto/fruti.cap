@echo off
setlocal
cd /d "%~dp0"
if not defined FRUTINOVELAS_MY_CONTENT_DIR set "FRUTINOVELAS_MY_CONTENT_DIR=%~dp0..\..\my content"
if not exist "%FRUTINOVELAS_MY_CONTENT_DIR%\seleccionar_python_bot.bat" (
  echo No se encontro My Content. Define FRUTINOVELAS_MY_CONTENT_DIR con su carpeta.
  pause
  exit /b 1
)
call "%FRUTINOVELAS_MY_CONTENT_DIR%\seleccionar_python_bot.bat"
if not defined BOT_PYTHON (
  echo No se encontro el Python del bot My Content.
  pause
  exit /b 1
)
"%BOT_PYTHON%" "%~dp0scripts\flow_mycontent_browser.py" --source "%FRUTINOVELAS_MY_CONTENT_DIR%" --login
pause
