"""MCP local: guías, prompts y preparación de imágenes mediante la API de Studio."""

import argparse
import ipaddress
import json

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from frutinovelas.guidance import Preset, Task, get_guidance, guidance_catalog, read_guide
from frutinovelas.mcp_studio import register_studio_tools
from frutinovelas.prompts import H3Draft, ImageDraft, LintRequest, compile_h3, compile_image, lint_h3


def create_server() -> MCPServer:
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
    parser.add_argument("--host", type=_loopback_host, default="127.0.0.1")
    parser.add_argument("--port", type=_port, default=8766)
    args = parser.parse_args(argv)
    options = {}
    if args.transport == "streamable-http":
        options = {
            "host": args.host,
            "port": args.port,
            "streamable_http_path": "/mcp",
            "stateless_http": True,
        }
    create_server().run(transport=args.transport, **options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
