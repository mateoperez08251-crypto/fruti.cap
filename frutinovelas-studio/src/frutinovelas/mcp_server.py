"""MCP local de preparación de prompts. No accede a escenas ni ejecuta generaciones."""

import json

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from frutinovelas.guidance import Preset, Task, get_guidance, guidance_catalog, read_guide
from frutinovelas.prompts import H3Draft, ImageDraft, LintRequest, compile_h3, compile_image, lint_h3


def create_server() -> MCPServer:
    server = MCPServer(
        "FRUTINOVELAS Prompts",
        instructions=(
            "Prepara y revisa prompts. Al iniciar una tarea de dirección, consulta get_directing_guidance "
            "con task y preset antes de redactar. Usa preset frutinovelas para las preferencias del proyecto "
            "o general para otros sujetos y estilos. No cargar example-story salvo que se retome ese arco. "
            "Las guías son consultables; no entrenan al modelo ni crean memoria automática. "
            "No genera imágenes/videos ni guarda escenas. Conserva diálogos literales y verifica las imágenes."
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

    return server


def main() -> int:
    create_server().run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
