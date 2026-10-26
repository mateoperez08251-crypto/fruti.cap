@echo off
rem Rompe-Camaras - DEMO (camara fake + selftest)
if exist "d:\fruti.cap\frutinovelas-studio\.venv\Scripts\python.exe" (
  "d:\fruti.cap\frutinovelas-studio\.venv\Scripts\python.exe" "%~dp0romper_camaras.py" demo %*
  exit /b
)
python "%~dp0romper_camaras.py" demo %*