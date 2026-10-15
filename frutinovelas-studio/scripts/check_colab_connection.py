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
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from validate_workflows import detect_format

UA = "FRUTINOVELAS-Studio/0.1"
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_NAME = re.compile(r"[A-Za-z0-9_.-]+\.api\.json")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Un cambio de host no debe recibir la cabecera Authorization.
        return None


def request(url: str, token: str | None = None, timeout: float = 30.0) -> tuple[int, bytes]:
    headers = {"User-Agent": UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prueba la conexión con ComfyUI en Colab")
    ap.add_argument("--url", required=True, help="URL pública que muestra la celda 9")
    ap.add_argument("--out", default=str(ROOT / "workflows" / "api"), help="Carpeta para los flujos API")
    args = ap.parse_args(argv)

    base = args.url.strip().rstrip("/")
    try:
        parts = urlsplit(base)
        valid = (
            parts.scheme == "https"
            and bool(parts.hostname)
            and parts.port != 0
            and not (parts.username or parts.password or parts.query or parts.fragment)
        )
    except ValueError:
        valid = False
    if not valid:
        print("ERROR: usa una URL https:// válida, sin credenciales, query ni fragmento.")
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
            print(
                f"    ERROR {st}: ¿está en marcha la celda 8 de la libreta? (RunPod: ¿puerto 8189 expuesto?)"
            )
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
        if st != 200:
            print(f"    ERROR {st}: identidad del servidor no disponible.")
            return 1
        ident = json.loads(body)
        if not isinstance(ident, dict) or not isinstance(ident.get("workflows"), dict):
            print("    ERROR: identidad sin inventario de flujos verificable.")
            return 1
        print(
            f"    ComfyUI {ident.get('comfyui_version')} · perfil {ident.get('perfil_video')}"
            f" · compatibilidad: {ident.get('estado_compatibilidad')}"
        )

        paso(4, "Estado de ComfyUI (/system_stats)")
        st, body = request(base + "/system_stats", token)
        if st != 200:
            print(f"    ERROR {st}")
            return 1
        stats = json.loads(body)
        if not isinstance(stats, dict) or not isinstance(stats.get("system"), dict):
            print("    ERROR: ComfyUI devolvió estadísticas no válidas.")
            return 1
        for dev in stats.get("devices", []):
            print(f"    GPU {dev.get('name')} · VRAM {int(dev.get('vram_total', 0)) / 2**30:.1f} GB")

        paso(5, "Flujos publicados")
        st, body = request(base + "/frutinovelas/workflows", token)
        listing = json.loads(body) if st == 200 else {}
        nombres = listing.get("workflows", []) if isinstance(listing, dict) else []
        if not isinstance(nombres, list) or not nombres:
            print("    ERROR: no hay flujos API publicados (revisa la celda 7B).")
            return 1

        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        esperados = ident.get("workflows", {})
        for nombre in nombres:
            if (
                not isinstance(nombre, str)
                or not WORKFLOW_NAME.fullmatch(nombre)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", str(esperados.get(nombre, "")))
            ):
                print(
                    "    ERROR: inventario con nombre o SHA-256 no válido. Ejecuta fruti start en el servidor."
                )
                return 1
        paso(6, f"Descargando flujos a {out}")
        for nombre in nombres:
            st, body = request(f"{base}/frutinovelas/workflows/{nombre}", token, timeout=60)
            if st != 200:
                print(f"    ERROR {st} en {nombre}")
                return 1
            digest = hashlib.sha256(body).hexdigest()
            esperado = esperados.get(nombre)
            if digest != esperado.lower():
                print(
                    f"    ERROR: {nombre} no coincide con la identidad del servidor ({digest[:12]} ≠ {esperado[:12]})."
                )
                return 1
            destino = out / nombre
            graph = json.loads(body)
            if detect_format(graph) != "api":
                print(f"    ERROR: {nombre} no es un grafo API válido.")
                return 1
            if destino.is_symlink() or destino.resolve().parent != out.resolve():
                print("    ERROR: el destino sale de la carpeta de flujos.")
                return 1
            temporal = destino.with_suffix(destino.suffix + ".partial")
            if temporal.is_symlink():
                print("    ERROR: el archivo temporal es un enlace simbólico.")
                return 1
            temporal.write_bytes(body)
            temporal.replace(destino)
            print(f"    ✓ {nombre} ({len(graph)} nodos, SHA-256 verificado)")
    except (urllib.error.URLError, TimeoutError):
        print("ERROR de red. ¿Cambió la URL, se desconectó Colab o se detuvo el pod?")
        return 1
    except (OSError, ValueError, TypeError, AttributeError):
        print("ERROR: respuesta del servidor no válida o carpeta de destino sin permisos.")
        return 1

    print("\nConexión correcta. Usa esta URL y el token en FRUTINOVELAS Studio → Conexiones → ComfyUI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
