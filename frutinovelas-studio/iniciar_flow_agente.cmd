@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m uv sync --extra flow-agent --frozen
if errorlevel 1 goto error
py -3.12 -m uv run --extra flow-agent --frozen frutinovelas-flow-agent serve
if errorlevel 1 goto error
exit /b 0
:error
echo No se pudo iniciar el agente. Revisa docs\FLOW_AUTOMATION.md.
pause
exit /b 1
