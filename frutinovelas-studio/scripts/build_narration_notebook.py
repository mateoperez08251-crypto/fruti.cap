"""Build a self-contained CPU-only Colab montage notebook from reviewed sources."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "FRUTINOVELAS_Montaje_Colab.ipynb"


def build():
    sources = {name: (ROOT / "scripts" / name).read_text(encoding="utf-8")
               for name in ("narrated_gateway.py", "narrated_server.py")}
    install = '''# @title 1. Preparar montador (CPU, sin modelos)
import sys, subprocess, shutil, urllib.request
from pathlib import Path
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "aiohttp>=3.10,<4", "Pillow>=10.4"], check=True)
if not shutil.which("ffmpeg"):
    subprocess.run(["apt-get", "update", "-qq"], check=True)
    subprocess.run(["apt-get", "install", "-y", "-qq", "ffmpeg"], check=True)
work = Path("/content/frutinovelas-montaje")
work.mkdir(parents=True, exist_ok=True)
binary = work / "cloudflared"
if not binary.exists():
    urllib.request.urlretrieve("https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64", binary)
    binary.chmod(0o700)
print("Montador preparado.")
'''
    launch = '''# @title 3. Conectar con Studio
import os, secrets, time, re, urllib.request, json
if "montage_server" in globals() and montage_server.poll() is None:
    raise RuntimeError("Ya hay un montador activo. Usa su conexión o reinicia el entorno antes de arrancar otro.")
montage_token = secrets.token_urlsafe(32)
environment = {**os.environ, "FRUTINOVELAS_NARRATION_TOKEN": montage_token}
server_log = (work / "server.log").open("w")
montage_server = subprocess.Popen([sys.executable, str(work / "narrated_server.py"), "--root", str(work / "data"), "--port", "8199"], env=environment, stdout=server_log, stderr=subprocess.STDOUT)
for _ in range(40):
    try:
        req = urllib.request.Request("http://127.0.0.1:8199/frutinovelas/narration/capabilities", headers={"Authorization": "Bearer " + montage_token})
        capabilities = json.load(urllib.request.urlopen(req, timeout=2))
        if not capabilities.get("ffmpeg"):
            raise RuntimeError("FFmpeg no está disponible.")
        break
    except (OSError, ValueError):
        if montage_server.poll() is not None:
            raise RuntimeError("El montador no arrancó. Consulta /content/frutinovelas-montaje/server.log")
        time.sleep(.5)
else:
    raise RuntimeError("El montador no respondió a tiempo.")
tunnel_log = work / "tunnel.log"
tunnel_output = tunnel_log.open("w")
montage_tunnel = subprocess.Popen([str(binary), "tunnel", "--url", "http://127.0.0.1:8199", "--no-autoupdate"], stdout=tunnel_output, stderr=subprocess.STDOUT)
for _ in range(80):
    found = re.search(r"https://[a-z0-9-]+\\.trycloudflare\\.com", tunnel_log.read_text())
    if found:
        print("En Studio → Videos narrados → Conectar Colab para unir el video")
        print("URL:", found.group(0))
        print("Clave:", montage_token)
        print("Conserva esta clave en privado. Mantén Colab abierto; no requiere streaming SSE.")
        break
    time.sleep(.5)
else:
    raise RuntimeError("No apareció la URL del túnel. Consulta tunnel.log y vuelve a iniciar el entorno.")
'''
    def cell(kind, source, number):
        result = {"cell_type": kind, "id": f"montaje-{number}", "metadata": {}, "source": source.splitlines(keepends=True)}
        if kind == "code":
            result.update(execution_count=None, outputs=[])
        return result
    return {"nbformat": 4, "nbformat_minor": 5,
            "metadata": {"kernelspec": {"display_name": "Python 3", "name": "python3"}, "language_info": {"name": "python"}},
            "cells": [cell("markdown", "# FRUTINOVELAS · Montaje con audio\nCPU; sin modelos generativos. Conserva el audio maestro y ajusta imágenes o clips a cada toma (máximo cinco minutos). Un clip corto mantiene su último fotograma hasta el siguiente corte.\n\nEjecuta las tres celdas en orden. El entorno es temporal: descarga el resultado en Studio antes de cerrar Colab. No subas esta libreta ejecutada con la clave visible.\n", 0),
                      cell("code", install, 1),
                      cell("code", '# @title 2. Instalar servidor incluido\nsources = ' + repr(sources) + '\nfor name, source in sources.items():\n    (work / name).write_text(source, encoding="utf-8")\nprint("Servidor instalado.")\n', 2),
                      cell("code", launch, 3)]}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(OUT)
