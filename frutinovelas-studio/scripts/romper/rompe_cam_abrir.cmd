@echo off
rem Rompe-Camaras - ABRIR camara ya rompeda
rem Uso:  rompe_cam_abrir.cmd -ip 192.168.1.50 -u admin -p admin123
if exist "d:\fruti.cap\frutinovelas-studio\.venv\Scripts\python.exe" (
  "d:\fruti.cap\frutinovelas-studio\.venv\Scripts\python.exe" "%~dp0romper_camaras.py" abrir %*
  exit /b
)
python "%~dp0romper_camaras.py" abrir %*