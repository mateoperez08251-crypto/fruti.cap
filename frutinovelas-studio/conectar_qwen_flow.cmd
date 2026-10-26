@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Inicia Studio una vez con iniciar.cmd para preparar el entorno.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m frutinovelas.flow_agent vision-connect
pause
