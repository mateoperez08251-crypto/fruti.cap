"""MCP local: guías, prompts y preparación de imágenes mediante la API de Studio."""

import argparse
import ipaddress
import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from frutinovelas.config import get_settings, reset_settings_cache
from frutinovelas.guidance import Preset, Task, get_guidance, guidance_catalog, read_guide
from frutinovelas.mcp_studio import register_studio_tools
from frutinovelas.prompts import H3Draft, ImageDraft, LintRequest, compile_h3, compile_image, lint_h3


def create_server(*, include_flow: bool = False) -> MCPServer:
    server = MCPServer(
        "FRUTINOVELAS Prompts",
        instructions=(
            "Prepara y revisa prompts. Al iniciar una tarea de dirección, consulta get_directing_guidance "
            "con task y preset antes de redactar. Usa preset frutinovelas para las preferencias del proyecto "
            "o general para otros sujetos y estilos. No cargar example-story salvo que se retome ese arco. "
            "Las guías son consultables; no entrenan al modelo ni crean memoria automática. "
            "Las herramientas Studio necesitan la API local abierta. Guion, prompt de imagen y prompt H3 son distintos. "
            "Inspecciona las referencias e imágenes antes de redactar. Encola Qwen solo si el usuario pidió generar. "
            "La revisión manual es predeterminada; solo usa aprobación y animación automáticas si el usuario lo pidió. Inspecciona inicio y final y estima y guarda los segundos para las acciones y el diálogo (4–15 s); conserva el ajuste manual. "
            "Conserva diálogos y prompts literales."
        ),
    )
    annotations = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    @server.tool(annotations=annotations)
    def get_directing_guidance(
        task: Task = "animation", preset: Preset = "frutinovelas", include_example_story: bool = False
    ) -> dict:
        """Leer primero: skill, dirección, modelos y preferencias para cualquier escena. La historia de ejemplo es opcional."""
        return get_guidance(task, preset, include_example_story)

    @server.resource("frutinovelas://guides", mime_type="application/json")
    def guides_catalog() -> str:
        """Catálogo de guías y skills del proyecto con URIs MCP."""
        return json.dumps(guidance_catalog(), ensure_ascii=False)

    @server.resource("frutinovelas://guides/{name}", mime_type="text/markdown")
    def directing_guide(name: str) -> str:
        """Leer una guía por su nombre publicado en el catálogo, sin acceso a archivos arbitrarios."""
        return read_guide(name)

    @server.prompt()
    def direct_scene(request: str, task: Task = "animation", preset: Preset = "frutinovelas") -> str:
        """Preparar el contexto de dirección para una escena nueva, sin cargar historias ajenas."""
        context = get_guidance(task, preset)
        return (
            context["scope"]
            + "\n\n"
            + "\n\n".join(guide["content"] for guide in context["guides"])
            + "\n\n## Petición de la escena actual\n\n"
            + request
        )

    @server.tool(annotations=annotations)
    def prepare_h3_prompt(draft: H3Draft) -> dict:
        """Compilar dirección audiovisual I2VA/FL2VA con cronología y voces explícitas."""
        return compile_h3(draft).model_dump()

    @server.tool(annotations=annotations)
    def prepare_image_prompt(draft: ImageDraft) -> dict:
        """Preparar una imagen inicial Qwen 2512 o una edición Qwen 2511."""
        return compile_image(draft).model_dump()

    @server.tool(annotations=annotations)
    def review_h3_prompt(draft: LintRequest) -> dict:
        """Revisión textual orientativa; no reemplaza inspección de imágenes o video."""
        return {"issues": [issue.model_dump() for issue in lint_h3(draft)]}

    register_studio_tools(server)
    if include_flow:
        from frutinovelas.mcp_flow import register_flow_tools
        register_flow_tools(server, annotations, ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
    return server


def _loopback_host(value: str) -> str:
    if value == "localhost":
        return "127.0.0.1"
    try:
        if ipaddress.ip_address(value).is_loopback:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(
        "Usa una dirección loopback, por ejemplo 127.0.0.1; conecta mediante un túnel privado."
    )


def _port(value: str) -> int:
    try:
        number = int(value)
        if 1 <= number <= 65535:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("El puerto debe estar entre 1 y 65535.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCP de guías y prompts, independiente de ComfyUI.")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--directory", type=Path, help="Carpeta de Studio cuya configuración .env debe utilizarse.")
    parser.add_argument("--api-port", type=_port, help="Puerto efectivo de la API local de Studio.")
    parser.add_argument("--host", type=_loopback_host)
    parser.add_argument("--port", type=_port)
    args = parser.parse_args(argv)
    if args.directory is not None:
        try:
            os.chdir(args.directory.expanduser().resolve(strict=True))
        except OSError:
            parser.error("No se pudo abrir la carpeta indicada en --directory.")
        reset_settings_cache()
    settings = get_settings()
    if args.api_port is not None:
        settings.api_port = args.api_port
    try:
        host = _loopback_host(args.host if args.host is not None else settings.mcp_host)
        port = _port(str(args.port if args.port is not None else settings.mcp_port))
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    options = {}
    if args.transport == "streamable-http":
        options = {
            "host": host,
            "port": port,
            "streamable_http_path": "/mcp",
            "stateless_http": True,
        }
    if args.transport == "streamable-http" and settings.mcp_token:
        import uvicorn

        from frutinovelas.mcp_flow import BearerMiddleware
        app = create_server(include_flow=True).streamable_http_app(host=host, stateless_http=True)
        uvicorn.run(BearerMiddleware(app, settings.mcp_token), host=host, port=port, proxy_headers=False)
    else:
        # Public/unauthenticated test tunnels must never expose desktop automation.
        server = create_server(include_flow=True) if args.transport == "stdio" else create_server()
        server.run(transport=args.transport, **options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
