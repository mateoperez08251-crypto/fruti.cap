"""Configuración local de clientes MCP y diagnóstico de protocolo, sin credenciales."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from frutinovelas.config import Settings, get_settings


class McpServerCommand(BaseModel):
    command: str
    args: list[str]
    env: dict[str, str]


class ClaudeDesktopConfig(BaseModel):
    mcpServers: dict[str, McpServerCommand]


class McpConnectionInfo(BaseModel):
    local_url: str
    host: str
    port: int
    authentication: Literal["none"] = "none"
    shell: Literal["PowerShell", "Terminal"]
    http_command: str
    stdio_command: str
    claude_desktop_config: ClaudeDesktopConfig
    claude_config_path: str | None
    api_token_configured: bool


class McpConnectionStatus(BaseModel):
    state: Literal["ready", "unreachable", "incompatible"]
    detail: str
    server_name: str | None = None
    tools_count: int | None = None
    local_url: str
    checked_at: str


def local_address(settings: Settings) -> tuple[str, int, str]:
    """El diagnóstico solo puede dirigirse al MCP del equipo, nunca a URLs del cliente."""
    host = "127.0.0.1" if settings.mcp_host == "localhost" else settings.mcp_host
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("El host MCP debe ser una dirección loopback.") from exc
    if not address.is_loopback:
        raise ValueError("El host MCP debe ser una dirección loopback.")
    if not 1 <= settings.mcp_port <= 65535:
        raise ValueError("El puerto MCP debe estar entre 1 y 65535.")
    url_host = f"[{host}]" if address.version == 6 else host
    return host, settings.mcp_port, f"http://{url_host}:{settings.mcp_port}/mcp"


def shell_command(arguments: list[str], *, windows: bool) -> str:
    if windows:
        # Literales de PowerShell: protegen espacios, comillas, $, %, & y otros caracteres.
        return "& " + " ".join("'" + argument.replace("'", "''") + "'" for argument in arguments)
    return shlex.join(arguments)


def connection_info() -> McpConnectionInfo:
    settings = get_settings()
    host, port, url = local_address(settings)
    # Claude puede arrancar desde otra carpeta. Reutilizar el cwd de Studio conserva su .env.
    directory = str(Path.cwd().resolve())
    executable = str(Path(sys.executable).absolute())
    base_arguments = ["-m", "frutinovelas.mcp_server", "--directory", directory]
    stdio_arguments = [*base_arguments, "--transport", "stdio"]
    http_arguments = [
        *base_arguments,
        "--transport", "streamable-http",
        "--host", host,
        "--port", str(port),
        "--api-port", str(settings.api_port),
    ]
    windows = sys.platform == "win32"
    if windows:
        appdata = os.environ.get("APPDATA")
        config_path = str(Path(appdata) / "Claude" / "claude_desktop_config.json") if appdata else r"%APPDATA%\Claude\claude_desktop_config.json"
    elif sys.platform == "darwin":
        config_path = str(Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    else:
        config_path = None
    return McpConnectionInfo(
        local_url=url,
        host=host,
        port=port,
        shell="PowerShell" if windows else "Terminal",
        http_command=shell_command([executable, *http_arguments], windows=windows),
        stdio_command=shell_command([executable, *stdio_arguments], windows=windows),
        claude_desktop_config=ClaudeDesktopConfig(mcpServers={
            "frutinovelas": McpServerCommand(
                command=executable,
                args=stdio_arguments,
                # Solo se exporta el puerto. Los tokens permanecen en la configuración local.
                env={"FRUTINOVELAS_API_PORT": str(settings.api_port)},
            )
        }),
        claude_config_path=config_path,
        api_token_configured=bool(settings.api_token),
    )


async def connection_status() -> McpConnectionStatus:
    """Inicializa MCP y lista herramientas; no llama herramientas ni inicia procesos."""
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    _, _, url = local_address(get_settings())
    try:
        async with asyncio.timeout(6):
            async with httpx2.AsyncClient(
                trust_env=False, follow_redirects=False, timeout=httpx2.Timeout(2.5, connect=1.5)
            ) as client:
                async with streamable_http_client(url, http_client=client) as streams:
                    async with ClientSession(*streams) as session:
                        initialized = await session.initialize()
                        listing = await session.list_tools()
        server_info = getattr(initialized, "server_info", None)
        if server_info is None:
            server_info = getattr(initialized, "serverInfo", None)
        name = getattr(server_info, "name", None)
        names = {tool.name for tool in listing.tools}
        expected = {"get_directing_guidance", "list_studio_projects"}
        ready = name == "FRUTINOVELAS Prompts" and expected.issubset(names)
        return McpConnectionStatus(
            state="ready" if ready else "incompatible",
            detail=(
                "El MCP local de Frutinovelas responde y publica sus herramientas."
                if ready else
                "El puerto responde como MCP, pero no corresponde al servidor actualizado de Frutinovelas."
            ),
            server_name=name,
            tools_count=len(listing.tools),
            local_url=url,
            checked_at=datetime.now(UTC).isoformat(),
        )
    except Exception:
        # Las excepciones anidadas del transporte pueden incluir contenido del servidor.
        # No se devuelve ni registra ese contenido en el modal.
        return McpConnectionStatus(
            state="unreachable",
            detail="No se pudo completar la conexión MCP local. Inicia el comando HTTP y comprueba su puerto.",
            local_url=url,
            checked_at=datetime.now(UTC).isoformat(),
        )
