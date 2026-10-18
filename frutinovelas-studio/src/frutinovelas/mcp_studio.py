"""Additive MCP tools for the running local Studio API; no credential changes."""

import base64
import json
from typing import Literal
from urllib.parse import quote

import httpx
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ImageContent, TextContent, ToolAnnotations

from frutinovelas.config import get_settings
from frutinovelas.mcp_chapters import register_chapter_tools
from frutinovelas.mcp_controls import register_studio_controls
from frutinovelas.schemas import SceneAudioGuide


def _id(value):
    return quote(value, safe="")


def studio_request(method, path, body=None, raw=False):
    settings = get_settings()
    headers = {"Authorization": "Bearer " + settings.api_token} if settings.api_token else {}
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{settings.api_port}/api/v1/",
            timeout=150,
            trust_env=False,
            follow_redirects=False,
            headers=headers,
        ) as client:
            response = (
                client.request(method, path.lstrip("/"), json=body)
                if body is not None
                else client.request(method, path.lstrip("/"))
            )
        if not response.is_success:
            detail = response.json().get("detail", "No se pudo completar la operación en Studio.")
            raise ToolError(str(detail))
        return response.content if raw else response.json()
    except httpx.HTTPError as exc:
        raise ToolError(
            "Studio no responde. Abre el programa local; no hace falta regenerar el token MCP."
        ) from exc


def register_studio_tools(server):
    read = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    write = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    register_chapter_tools(server, write, studio_request)
    register_studio_controls(server, read, write, studio_request)

    @server.tool(annotations=write)
    def import_studio_image(request_id: str, filename: str, mime_type: str | None = None,
                            content_base64: str | None = None, url: str | None = None) -> dict:
        """Importar PNG/JPEG/WebP externo (base64 máximo 4 MiB o HTTPS pública hasta 40 MiB). No asigna fotograma ni ejecuta GPU. Repetir request_id reutiliza la importación."""
        return studio_request("POST", "assets/import", {
            "request_id": request_id, "filename": filename, "mime_type": mime_type,
            "content_base64": content_base64, "url": url,
        })

    @server.tool(annotations=read)
    def list_studio_projects() -> list[dict]:
        """Obtener IDs reales de los proyectos. No deducirlos de títulos."""
        return studio_request("GET", "projects")

    @server.tool(annotations=read)
    def list_studio_chapters(project_id: str) -> list[dict]:
        """IDs y resúmenes de capítulos. Lee el guion una vez con get_scene_preparation."""
        return [
            {k: chapter[k] for k in ("id", "title", "revision", "scene_count", "ready_count")}
            for chapter in studio_request("GET", f"projects/{_id(project_id)}/chapters")
        ]

    @server.tool(annotations=read)
    def list_studio_scenes(chapter_id: str) -> list[dict]:
        """Escenas ordenadas, ambos prompts y reparto con referencias congeladas."""
        return studio_request("GET", f"chapters/{_id(chapter_id)}/scenes")

    @server.tool(annotations=read)
    def list_project_characters(project_id: str) -> list[dict]:
        """Biblioteca del proyecto, referencias visuales y muestras de voz reutilizables. Elegir voice_character_ids en la escena permite generar diálogo nuevo con H3 Ref2VA."""
        return studio_request("GET", f"projects/{_id(project_id)}/characters")

    @server.tool(annotations=read)
    def inspect_studio_image(asset_id: str) -> list[TextContent | ImageContent]:
        """Ver una referencia o resultado aprobado antes de describirlo o redactar la animación."""
        metadata = studio_request("GET", f"assets/{_id(asset_id)}")
        image = studio_request("GET", f"assets/{_id(asset_id)}/thumb?size=1024", raw=True)
        return [
            TextContent(text=json.dumps(metadata, ensure_ascii=False)),
            ImageContent(data=base64.b64encode(image).decode(), mime_type="image/webp"),
        ]

    @server.tool(annotations=read)
    def get_scene_preparation(scene_id: str, include_chapter_context: bool = True) -> dict:
        """Leer escena, ambos prompts y referencias. Incluir guion y continuidad una vez; después usar false para ahorrar contexto."""
        scene = studio_request("GET", f"scenes/{_id(scene_id)}")
        chapter = (
            studio_request("GET", f"chapters/{_id(scene['chapter_id'])}") if include_chapter_context else None
        )
        return {
            "scene": scene,
            "chapter": chapter,
            "next_steps": "Lee guías, inspecciona referencias, guarda preparación. Genera imagen solo bajo petición; respeta revisión manual por defecto y aprobación automática solo si el usuario la activó. Inspecciona los fotogramas de inicio/final y estima los segundos necesarios para la acción y el diálogo; guarda esa duración con save_scene_preparation (4–15 segundos). No deduzcas la duración solo del número de imágenes. Después inspecciona la imagen aprobada y redacta H3 según guion y continuidad.",
        }

    @server.tool(annotations=write)
    def save_scene_preparation(
        scene_id: str,
        expected_revision: int,
        image_prompt: str | None = None,
        animation_prompt: str | None = None,
        character_ids: list[str] | None = None,
        duration_seconds: float | None = None,
        image_approval: Literal["manual", "automatic"] | None = None,
        audio_guides: list[SceneAudioGuide] | None = None,
        voice_character_ids: list[str] | None = None,
    ) -> dict:
        """Guardar preparación sin generar. voice_character_ids selecciona hasta 3 muestras guardadas para decir diálogos nuevos del animation_prompt con H3 Ref2VA (2–15 s cada muestra; total ≤15 s). Alternativa: audio_guides contiene diálogos ya grabados con asset_id, character_id opcional y start_seconds. Los dos modos son excluyentes. Omitir un argumento conserva su selección; [] la quita. automatic solo bajo petición explícita del usuario."""
        scene = studio_request("GET", f"scenes/{_id(scene_id)}")
        if scene["revision"] != expected_revision:
            raise ToolError("La escena cambió. Vuelve a leerla antes de guardar.")
        body = {"expected_revision": expected_revision}
        if duration_seconds is not None:
            if not 4 <= duration_seconds <= 15:
                raise ToolError("Este perfil admite entre 4 y 15 segundos por clip.")
            body["duration_seconds"] = duration_seconds
        if (
            image_prompt is not None
            or character_ids is not None
            or image_approval is not None
            or audio_guides is not None
            or voice_character_ids is not None
        ):
            parameters = dict(scene["parameters"])
            if image_prompt is not None:
                parameters["image_prompt"] = image_prompt
            if character_ids is not None:
                parameters["character_ids"] = character_ids
            if image_approval is not None:
                parameters["image_approval"] = image_approval
            if audio_guides is not None:
                parameters["audio_guides"] = [guide.model_dump() for guide in audio_guides]
            if voice_character_ids is not None:
                parameters["voice_character_ids"] = voice_character_ids
            body["parameters"] = parameters
        if animation_prompt is not None:
            body["prompt"] = animation_prompt
        return studio_request("PATCH", f"scenes/{_id(scene_id)}", body)

    @server.tool(annotations=write)
    def request_scene_image(
        scene_id: str, expected_revision: int, request_id: str, auto_animate: bool = False
    ) -> dict:
        """USA GPU: solo si el usuario pidió generar. Encola Qwen con las referencias guardadas, sin esperar inferencia. Usar UUID único y repetirlo al reintentar. En manual espera aprobación; en automatic asigna inicio. auto_animate=true requiere modo automatic y solicitud explícita para generar también video."""
        return studio_request(
            "POST",
            f"scenes/{_id(scene_id)}/generate-image",
            {"expected_revision": expected_revision, "request_id": request_id, "auto_animate": auto_animate},
        )

    @server.tool(annotations=read)
    def list_scene_images(scene_id: str) -> list[dict]:
        """Trabajos Qwen, resultado y referencias exactas; no envía generaciones nuevas."""
        return studio_request("GET", f"scenes/{_id(scene_id)}/image-generations")

    @server.tool(annotations=write)
    def approve_scene_image(
        job_id: str, expected_revision: int, role: Literal["start", "end"] = "start"
    ) -> dict:
        """Asignar una imagen SOLO tras aprobación explícita del usuario. No aprobarla por cuenta del asistente ni iniciar video."""
        return studio_request(
            "POST",
            f"image-generations/{_id(job_id)}/approve",
            {"expected_revision": expected_revision, "role": role},
        )

    @server.tool(annotations=write)
    def request_chapter_render(
        chapter_id: str,
        expected_revision: int,
        scene_revisions: dict[str, int],
        request_id: str,
        automatic_approval: bool,
    ) -> dict:
        """USA GPU: solo con petición expresa del usuario de generación completa automática. Usa ambos prompts y duraciones guardados; imagen -> inicio -> video por escena, luego montaje FFmpeg. Repetir el mismo UUID al reintentar. No evalúa calidad ni crea prompts por sí solo."""
        if not automatic_approval:
            raise ToolError(
                "El capítulo automático necesita aprobación automática explícita para este proceso."
            )
        return studio_request(
            "POST",
            f"chapters/{_id(chapter_id)}/render",
            dict(
                expected_revision=expected_revision,
                scene_revisions=scene_revisions,
                request_id=request_id,
                automatic_approval=True,
            ),
        )

    @server.tool(annotations=read)
    def list_chapter_renders(chapter_id: str) -> list[dict]:
        """Consultar estado y video final de los procesos automáticos sin enviar generaciones nuevas."""
        return studio_request("GET", f"chapters/{_id(chapter_id)}/renders")
