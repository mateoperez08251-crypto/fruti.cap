@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Inicia Studio una vez con iniciar.cmd para preparar el entorno.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\configurar_qwen_puente.py
pause
