@echo off
rem Rompe-Camaras - SCAN de red
rem Uso:  rompe_cam_scan.cmd -red 192.168.1.0/24 [-p 80,8080]
if exist "d:\fruti.cap\frutinovelas-studio\.venv\Scripts\python.exe" (
  "d:\fruti.cap\frutinovelas-studio\.venv\Scripts\python.exe" "%~dp0romper_camaras.py" scan %*
  exit /b
)
python "%~dp0romper_camaras.py" scan %*