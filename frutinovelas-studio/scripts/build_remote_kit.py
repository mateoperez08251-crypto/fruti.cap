"""Empaqueta el kit remoto (RunPod / Linux) en ``dist/frutinovelas-kit.tar.gz``.

El paquete contiene solo lo necesario para ``fruti_remote.py``: scripts, manifiesto,
perfiles y el flujo H3 del usuario sin modificar (se verifica su SHA-256). Sin secretos,
modelos ni datos. Uso::

    uv run python scripts/build_remote_kit.py
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "frutinovelas-kit.tar.gz"
PREFIX = "frutinovelas-kit"
FILES = {
    "scripts/fruti_remote.py": 0o755,
    "scripts/validate_workflows.py": 0o644,
    "scripts/export_workflow_api.py": 0o644,
    "scripts/comfy_gateway.py": 0o644,
    "scripts/narrated_gateway.py": 0o644,
    "config/models_manifest.lock.json": 0o644,
    "config/workflow_profiles.json": 0o644,
    "src/frutinovelas/__init__.py": 0o644,
    "src/frutinovelas/services/__init__.py": 0o644,
    "src/frutinovelas/services/voice_workflow.py": 0o644,
}
UI = "workflows/H3_EQUILIBRADO_9x16_INICIO_FINAL.ui.json"

LEEME = """FRUTINOVELAS · kit remoto (RunPod / Linux con GPU NVIDIA)

Primera vez (en la terminal del pod, dentro de /workspace):
  tar -xzf frutinovelas-kit.tar.gz
  python3 frutinovelas-kit/scripts/fruti_remote.py setup

Después existe el atajo «fruti»:
  fruti status                 estado de ComfyUI, gateway y URL pública
  fruti token --mostrar        token para pegar en el programa
  fruti test --modo i2va       primera prueba real (5 s)
  fruti logs comfyui -f        logs en directo
  fruti stop                   detener servicios
  fruti start                  arrancar de nuevo (p. ej. tras reanudar el pod)

Para generar diálogos nuevos con una muestra de voz por personaje:
  fruti models --voces-personajes si
  fruti start --voces-personajes si --reexportar
Descarga Ref2VA INT8 (20,97 GB adicionales) y reutiliza el encoder y los VAEs H3.
Después vuelve a Guardar y comprobar la conexión en Studio.

Si el atajo no existe (pod reiniciado): python3 /workspace/frutinovelas-kit/scripts/fruti_remote.py start
Guía completa: docs/RUNPOD.md del repositorio.
"""


def add(tar: tarfile.TarFile, name: str, data: bytes, mode: int) -> None:
    info = tarfile.TarInfo(f"{PREFIX}/{name}")
    info.size = len(data)
    info.mode = mode
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(data))


def main() -> int:
    profiles = json.loads((ROOT / "config" / "workflow_profiles.json").read_text(encoding="utf-8"))
    ui_bytes = (ROOT / UI).read_bytes()
    if hashlib.sha256(ui_bytes).hexdigest() != profiles["profiles"][0]["workflow_ui_sha256"]:
        raise SystemExit("El flujo H3 no coincide con el SHA-256 del perfil.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(OUT, "w:gz") as tar:
        for rel, mode in FILES.items():
            text = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
            add(tar, rel, text, mode)
        add(tar, UI, ui_bytes, 0o644)  # copia exacta, sin normalizar
        add(tar, "LEEME.txt", LEEME.encode("utf-8"), 0o644)
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"Kit generado: {OUT} ({OUT.stat().st_size / 1024:.0f} KB) · sha256 {digest[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
