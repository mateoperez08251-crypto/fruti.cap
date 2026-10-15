"""Comprueba desde el PC la conexión con el ComfyUI remoto (Colab o RunPod) a través del gateway.

Solo usa la biblioteca estándar. El token se lee de ``FRUTI_COMFY_TOKEN`` o se pide
sin eco; nunca se acepta por argumento (quedaría en el historial) ni se imprime.

    $env:FRUTI_COMFY_TOKEN = "..."
    uv run python scripts/check_colab_connection.py --url https://xxxx.trycloudflare.com

Pasos: /healthz → rechazo sin token → identidad → /system_stats → lista de flujos →
descarga de cada ``*.api.json`` a ``workflows/api/`` verificando su SHA-256.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

UA = "FRUTINOVELAS-Studio/0.1"
ROOT = Path(__file__).resolve().parents[1]


def request(url: str, token: str | None = None, timeout: float = 30.0) -> tuple[int, bytes]:
    headers = {"User-Agent": UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prueba la conexión con ComfyUI en Colab")
    ap.add_argument("--url", required=True, help="URL pública que muestra la celda 9")
    ap.add_argument("--out", default=str(ROOT / "workflows" / "api"), help="Carpeta para los flujos API")
    args = ap.parse_args(argv)

    base = args.url.strip().rstrip("/")
    if not base.startswith("https://"):
        print("ERROR: la URL debe empezar por https://")
        return 2
    token = os.environ.get("FRUTI_COMFY_TOKEN", "").strip() or getpass.getpass("Token del gateway: ").strip()
    if len(token) < 16:
        print("ERROR: token vacío o demasiado corto.")
        return 2

    def paso(n: int, texto: str) -> None:
        print(f"[{n}] {texto}")

    try:
        paso(1, "Gateway en línea (/healthz)")
        st, _ = request(base + "/healthz")
        if st != 200:
            print(f"    ERROR {st}: ¿está en marcha la celda 8 de la libreta? (RunPod: ¿puerto 8189 expuesto?)")
            return 1

        paso(2, "Rechaza peticiones sin token")
        st, _ = request(base + "/system_stats")
        if st != 401:
            print(f"    ERROR: se esperaba 401 y llegó {st}.")
            return 1

        paso(3, "Identidad del servidor")
        st, body = request(base + "/frutinovelas/identity", token)
        if st == 401:
            print("    ERROR: token incorrecto.")
            return 1
        ident = json.loads(body) if st == 200 else {}
        print(f"    ComfyUI {ident.get('comfyui_version')} · perfil {ident.get('perfil_video')}"
              f" · compatibilidad: {ident.get('estado_compatibilidad')}")

        paso(4, "Estado de ComfyUI (/system_stats)")
        st, body = request(base + "/system_stats", token)
        if st != 200:
            print(f"    ERROR {st}")
            return 1
        for dev in json.loads(body).get("devices", []):
            print(f"    GPU {dev.get('name')} · VRAM {int(dev.get('vram_total', 0)) / 2**30:.1f} GB")

        paso(5, "Flujos publicados")
        st, body = request(base + "/frutinovelas/workflows", token)
        nombres = json.loads(body).get("workflows", []) if st == 200 else []
        if not nombres:
            print("    ERROR: no hay flujos API publicados (revisa la celda 7B).")
            return 1

        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        esperados = ident.get("workflows", {})
        paso(6, f"Descargando flujos a {out}")
        for nombre in nombres:
            st, body = request(f"{base}/frutinovelas/workflows/{nombre}", token, timeout=60)
            if st != 200:
                print(f"    ERROR {st} en {nombre}")
                return 1
            digest = hashlib.sha256(body).hexdigest()
            esperado = esperados.get(nombre)
            if esperado and digest != esperado:
                print(f"    ERROR: {nombre} no coincide con la identidad del servidor ({digest[:12]} ≠ {esperado[:12]}).")
                return 1
            destino = out / nombre
            destino.write_bytes(body)
            estado = "SHA-256 verificado" if esperado else "sin SHA-256 de referencia"
            print(f"    ✓ {nombre} ({len(json.loads(body))} nodos, {estado})")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"ERROR de red: {exc}. ¿Cambió la URL, se desconectó Colab o se detuvo el pod?")
        return 1

    print("\nConexión correcta. Usa esta URL y el token en FRUTINOVELAS Studio → Conexiones → ComfyUI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
