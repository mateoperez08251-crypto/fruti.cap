@echo off
setlocal
cd /d "%~dp0"
node --version >nul 2>&1
if errorlevel 1 (
  echo Instala Node.js 22.12 o superior y vuelve a abrir este archivo.
  pause
  exit /b 1
)
py -3 -m uv --version >nul 2>&1
if errorlevel 1 (
  py -3 -m pip install uv
  if errorlevel 1 goto failed
)
py -3 -m uv sync --link-mode copy
if errorlevel 1 goto failed
if not exist frontend\node_modules (
  call npm.cmd --prefix frontend ci
  if errorlevel 1 goto failed
)
call npm.cmd --prefix frontend run build
if errorlevel 1 goto failed
py -3 -m uv run frutinovelas-api
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo No se pudo iniciar FRUTINOVELAS Studio. Copia el error mostrado arriba.
pause
exit /b 1
