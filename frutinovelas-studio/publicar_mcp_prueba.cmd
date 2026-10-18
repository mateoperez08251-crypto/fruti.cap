@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m uv run --frozen python scripts\public_mcp_tunnel.py
if errorlevel 1 (
  echo.
  echo La prueba publica no se inicio. Revisa el mensaje anterior.
  pause
)
