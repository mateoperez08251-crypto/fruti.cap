"""Connect Cline to local Windows tools and Studio without editing provider credentials."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

WINDOWS_MCP_VERSION = "0.8.5"


def server_entries(root: Path, uvx: str) -> dict:
    python = root / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise ValueError("Inicia Studio una vez para preparar su entorno Python.")
    return {
        "windows-desktop-qwen": {
            "command": uvx,
            "args": [f"windows-mcp=={WINDOWS_MCP_VERSION}", "serve", "--transport", "stdio"],
            "env": {"ANONYMIZED_TELEMETRY": "false"},
            "disabled": False,
            "timeout": 120,
        },
        "frutinovelas-studio": {
            "command": str(python),
            "args": ["-m", "frutinovelas.mcp_server", "--transport", "stdio", "--directory", str(root)],
            "disabled": False,
            "timeout": 120,
        },
    }


def merge_servers(current: dict, entries: dict) -> dict:
    if not isinstance(current, dict) or not isinstance(current.get("mcpServers", {}), dict):
        raise ValueError("La configuración MCP no tiene el formato esperado; no se modificó.")
    result = copy.deepcopy(current)
    servers = result.setdefault("mcpServers", {})
    for name, entry in entries.items():
        if name in servers and servers[name] != entry:
            raise ValueError(f"Ya hay una entrada distinta llamada {name}. No se sobrescribió.")
        servers[name] = entry
    return result


def install(settings: Path, entries: dict) -> Path | None:
    original = settings.read_bytes() if settings.exists() else None
    current = json.loads(original.decode("utf-8-sig")) if original is not None else {}
    updated = merge_servers(current, entries)
    if current == updated:
        return None
    settings.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="cline-mcp-", suffix=".tmp", dir=settings.parent)
    temporary = Path(name)
    backup = None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write((json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        # Avoid replacing concurrent edits from Cline or another installer.
        now = settings.read_bytes() if settings.exists() else None
        if now != original:
            raise ValueError("Cline cambió su configuración durante la preparación. Reintenta; no se sobrescribió.")
        if original is not None:
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
            backup = settings.with_name(settings.name + f".{stamp}.bak")
            with backup.open("xb") as stream:
                stream.write(original)
            backup.chmod(0o600)
        os.replace(temporary, settings)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


async def verify(entries: dict) -> dict[str, list[str]]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    result = {}
    for name, entry in entries.items():
        parameters = StdioServerParameters(
            command=entry["command"], args=entry["args"],
            env={**os.environ, **entry.get("env", {})},
        )
        async with asyncio.timeout(90):
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=60) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    result[name] = [tool.name for tool in tools.tools]
        if not result[name]:
            raise ValueError(f"{name} no publicó herramientas.")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Conectar Qwen/Cline al escritorio Windows y a Studio por stdio local.")
    parser.add_argument("--settings", type=Path, default=Path.home() / ".cline/data/settings/cline_mcp_settings.json")
    parser.add_argument("--install", action="store_true", help="Guardar las entradas tras comprobar los servidores.")
    args = parser.parse_args(argv)
    uvx = shutil.which("uvx")
    if not uvx:
        parser.error("No se encontró uvx. Instala uv o inicia Studio con su instalador habitual.")
    try:
        entries = server_entries(Path(__file__).resolve().parents[1], uvx)
        tools = asyncio.run(verify(entries))
        desktop = set(tools["windows-desktop-qwen"])
        required = {"Click", "Type", "Shortcut", "Snapshot", "PowerShell"}
        if not required <= desktop:
            raise ValueError("El servidor Windows no publicó las herramientas esperadas. No se modificó Cline.")
        for name, names in tools.items():
            print(f"{name}: {len(names)} herramientas comprobadas: " + ", ".join(names))
        if args.install:
            backup = install(args.settings, entries)
            print("Configuración Cline preparada:", args.settings)
            if backup:
                print("Copia anterior:", backup)
            print("Recarga los servidores MCP en Cline. La conexión del proveedor Qwen no se modificó.")
        else:
            print("Solo comprobación. Usa --install para guardar la configuración.")
        return 0
    except (OSError, ValueError, TimeoutError):
        print("No se completó la configuración. Comprueba los servidores y la estructura del archivo MCP; no se mostrarán datos privados.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
