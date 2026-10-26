@echo off
rem Rompe-Camaras - ATACAR una camara
rem Uso:  rompe_cam_attack.cmd -ip 192.168.1.50 [-p 80,8080] [-d dic.txt]
if exist "d:\fruti.cap\frutinovelas-studio\.venv\Scripts\python.exe" (
  "d:\fruti.cap\frutinovelas-studio\.venv\Scripts\python.exe" "%~dp0romper_camaras.py" attack %*
  exit /b
)
python "%~dp0romper_camaras.py" attack %*