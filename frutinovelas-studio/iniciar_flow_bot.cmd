@echo off
setlocal
cd /d "%~dp0"
rem Ejecutor Chromium de la cola Flow de Studio (modulo de navegador de My Content).
rem Requiere Studio abierto y Flow conectado en modo "navegador".
if not defined FRUTINOVELAS_MY_CONTENT_DIR set "FRUTINOVELAS_MY_CONTENT_DIR=%~dp0..\..\my content"
if not exist "%FRUTINOVELAS_MY_CONTENT_DIR%\seleccionar_python_bot.bat" (
  echo No se encontro My Content. Define FRUTINOVELAS_MY_CONTENT_DIR con su carpeta.
  pause
  exit /b 1
)
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Falta el entorno de Studio. Ejecuta iniciar.cmd una vez.
  pause
  exit /b 1
)
rem La credencial se pasa solo por el entorno de este proceso; no se escribe en disco.
for /f "usebackq delims=" %%K in (`""%~dp0.venv\Scripts\python.exe" "%~dp0scripts\flow_bot_key.py""`) do set "FRUTI_FLOW_BOT_KEY=%%K"
if not defined FRUTI_FLOW_BOT_KEY (
  echo No se pudo preparar la credencial local del bot.
  pause
  exit /b 1
)
call "%FRUTINOVELAS_MY_CONTENT_DIR%\seleccionar_python_bot.bat"
if not defined BOT_PYTHON (
  echo No se encontro el Python del bot My Content.
  pause
  exit /b 1
)
"%BOT_PYTHON%" "%~dp0scripts\flow_browser_bot.py" --source "%FRUTINOVELAS_MY_CONTENT_DIR%" %*
pause
