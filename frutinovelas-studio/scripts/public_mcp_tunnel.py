"""Servidor MCP local publicado temporalmente en un Cloudflare Quick Tunnel.

No despliega infraestructura y NO autentica a los clientes externos.
Se activa solo tras escribir PUBLICAR y termina al cerrar la consola.
"""
from __future__ import annotations

import argparse
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from frutinovelas.config import get_settings

QUICK_TUNNEL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


def public_mcp_url(line: str) -> str | None:
    """Extraer solamente el dominio Quick Tunnel que cloudflared anuncia."""
    match = QUICK_TUNNEL.search(line)
    return match.group(0).rstrip("/") + "/mcp" if match else None


def local_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.7)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def commands(directory: Path, port: int, api_port: int, cloudflared: str) -> tuple[list[str], list[str]]:
    """El MCP continúa escuchando SOLO en loopback incluso con el túnel público."""
    mcp = [
        sys.executable, "-m", "frutinovelas.mcp_server",
        "--directory", str(directory), "--transport", "streamable-http",
        "--host", "127.0.0.1", "--port", str(port), "--api-port", str(api_port),
    ]
    origin = f"http://127.0.0.1:{port}"
    # La cabecera Host del origen debe permanecer local para la protección anti-DNS-rebinding.
    cloud = [
        cloudflared, "tunnel", "--url", origin,
        "--http-host-header", f"127.0.0.1:{port}",
    ]
    return mcp, cloud


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publicar temporalmente el MCP SIN autenticación.")
    parser.add_argument("--existing-mcp", action="store_true", help="Reutilizar un MCP local que ya está iniciado.")
    parser.add_argument("--port", type=int, help="Puerto MCP local; por defecto usa la configuración de Studio.")
    parser.add_argument("--api-port", type=int, help="Puerto API; por defecto usa la configuración de Studio.")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    # Leer .env desde el mismo directorio de Studio, no desde otra carpeta de la consola.
    import os
    os.chdir(root)
    settings = get_settings()
    port = args.port if args.port is not None else settings.mcp_port
    api_port = args.api_port if args.api_port is not None else settings.api_port
    if not (1 <= port <= 65535 and 1 <= api_port <= 65535):
        parser.error("Los puertos deben estar entre 1 y 65535.")
    executable = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    if not executable:
        print("No se encontró cloudflared. Instálalo: winget install --id Cloudflare.cloudflared", file=sys.stderr)
        return 2

    print("\nMCP PÚBLICO DE PRUEBA — SIN AUTENTICACIÓN")
    print("Cualquier persona con el enlace podrá LEER, MODIFICAR o GENERAR con las herramientas MCP.")
    print("Utiliza proyectos descartables. NO compartas este enlace en redes ni guardes secretos en escenas.")
    print("Este proceso termina al pulsar Ctrl+C. No se abre directamente un puerto de Windows a Internet.\n")
    try:
        if input("Escribe PUBLICAR para confirmar la exposición temporal: ").strip() != "PUBLICAR":
            print("Cancelado: no se inició ningún túnel.")
            return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        return 1

    mcp_args, cloud_args = commands(root, port, api_port, executable)
    mcp_proc = None
    cloud_proc = None
    try:
        already = local_port_open(port)
        if already and not args.existing_mcp:
            print(f"El puerto {port} ya está ocupado. Si es TU MCP, ejecuta: python scripts/public_mcp_tunnel.py --existing-mcp")
            return 2
        if args.existing_mcp and not already:
            print(f"No hay MCP HTTP escuchando en 127.0.0.1:{port}. Inícialo primero.")
            return 2
        if not args.existing_mcp:
            mcp_proc = subprocess.Popen(mcp_args, cwd=root)
            for _ in range(50):
                if mcp_proc.poll() is not None:
                    print("El servidor MCP terminó inesperadamente; comprueba la salida anterior.")
                    return 2
                if local_port_open(port):
                    break
                time.sleep(0.1)
            else:
                print("El servidor MCP no abrió su puerto local.")
                return 2

        print(f"\nMCP local: http://127.0.0.1:{port}/mcp")
        print("Creando túnel HTTPS público temporal…")
        cloud_proc = subprocess.Popen(
            cloud_args, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", bufsize=1,
        )
        published = False
        assert cloud_proc.stdout is not None
        for line in cloud_proc.stdout:
            print(line.rstrip())
            url = public_mcp_url(line)
            if url and not published:
                print(f"\nURL MCP PÚBLICA PARA CHATGPT O CLAUDE: {url}")
                print("Selecciona conexión por URL (no Tunnel de OpenAI) y No authentication.")
                print("Pulsa Ctrl+C para desconectar el acceso público.\n")
                published = True
        return cloud_proc.wait()
    except KeyboardInterrupt:
        print("\nCerrando túnel de prueba…")
        return 0
    finally:
        stop(cloud_proc)
        stop(mcp_proc)


if __name__ == "__main__":
    raise SystemExit(main())
