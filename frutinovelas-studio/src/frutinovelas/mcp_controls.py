"""Controles MCP tipados para la API local de FRUTINOVELAS Studio.

Sin proxy arbitrario, shell, lectura de credenciales ni acceso al sistema de archivos.
Las llamadas mutadoras atraviesan validaciones, revisiones y auditoría de Studio.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid5

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations


def _id(value: str) -> str:
    from urllib.parse import quote
    return quote(value, safe="")


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ToolError("request_id debe ser un UUID válido.") from exc


def _fields(**values):
    return {name: value for name, value in values.items() if value is not None}


def _confirm(confirmed: bool):
    if confirmed is not True:
        raise ToolError("Se requiere confirmed=true para eliminar datos.")


def queue_chapter_images(chapter_id: str, request_id: str, request) -> dict:
    """Iniciar imágenes faltantes, con reintentos idempotentes y sin iniciar video."""
    namespace = UUID(_uuid(request_id))
    scenes = request("GET", f"chapters/{_id(chapter_id)}/scenes")
    if not 1 <= len(scenes) <= 60:
        raise ToolError("El capítulo necesita entre 1 y 60 escenas.")
    planned = []
    for s in scenes:
        if not (s.get("parameters", {}).get("image_prompt") or "").strip():
            raise ToolError(f"La escena «{s['title']}» no tiene prompt de imagen.")
        jobs = request("GET", f"scenes/{_id(s['id'])}/image-generations")
        current = jobs[0] if jobs else None
        if current and current["state"] not in ("failed", "completed"):
            planned.append((s, "existing_active"))
        elif current and current["state"] == "completed":
            planned.append((s, "existing_result"))
        else:
            planned.append((s, "queue"))
    results = []
    for s, action in planned:
        if action != "queue":
            results.append({"scene_id": s["id"], "action": action})
            continue
        scene_request = str(uuid5(namespace, s["id"]))
        try:
            job = request("POST", f"scenes/{_id(s['id'])}/generate-image", {
                "expected_revision": s["revision"], "request_id": scene_request,
                "auto_animate": False,
            })
            results.append({"scene_id": s["id"], "action": "queued", "job_id": job["id"]})
        except Exception as exc:
            results.append({"scene_id": s["id"], "action": "error", "detail": str(exc)[:240]})
            break
    return {"chapter_id": chapter_id, "results": results, "generation_type": "images_only",
            "enqueued": sum(x["action"] == "queued" for x in results)}


def queue_full_chapter(chapter_id: str, request_id: str, automatic_approval: bool, request) -> dict:
    if automatic_approval is not True:
        raise ToolError("Para generar videos sin revisión individual confirma automatic_approval=true.")
    chapter = request("GET", f"chapters/{_id(chapter_id)}")
    scenes = request("GET", f"chapters/{_id(chapter_id)}/scenes")
    if not 1 <= len(scenes) <= 60:
        raise ToolError("El capítulo necesita de 1 a 60 escenas.")
    for s in scenes:
        if not (s["prompt"] or "").strip() or not (s["parameters"].get("image_prompt") or "").strip():
            raise ToolError(f"Faltan prompts en «{s['title']}».")
        if not 4 <= s["duration_seconds"] <= 15:
            raise ToolError(f"Duración incompatible en «{s['title']}».")
    prior = request("GET", f"chapters/{_id(chapter_id)}/renders")
    for job in prior:
        if job["state"] not in ("completed", "failed"):
            return {"already_running": True, "render": job}
    return request("POST", f"chapters/{_id(chapter_id)}/render", {
        "request_id": _uuid(request_id), "expected_revision": chapter["revision"],
        "scene_revisions": {s["id"]: s["revision"] for s in scenes},
        "automatic_approval": True,
    })


def register_studio_controls(server, read, write, request):
    dangerous = ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
    )

    @server.tool(annotations=read)
    def get_studio_status() -> dict:
        """Verificar API, ComfyUI, GPU remota y FFmpeg; omite ruta local y secretos."""
        result = request("GET", "system/status")
        result.get("storage", {}).pop("data_dir", None)
        return result

    @server.tool(annotations=read)
    def get_comfy_connection() -> dict:
        """Ver configuración ComfyUI sin devolver token ni datos secretos."""
        data = request("GET", "comfy/connection")
        return {"configured": data.get("configured"), "has_token": data.get("has_token"),
                "url": data.get("url"), "profile": (data.get("identity") or {}).get("perfil_video")}

    @server.tool(annotations=write)
    def create_studio_project(name: str, language: str = "es", aspect_ratio: str = "9:16") -> dict:
        """Crear proyecto sin generar GPU."""
        return request("POST", "projects", {"name": name, "language": language, "aspect_ratio": aspect_ratio})

    @server.tool(annotations=write)
    def update_studio_project(project_id: str, name: str | None = None,
                              aspect_ratio: str | None = None, archived: bool | None = None) -> dict:
        """Renombrar, editar formato o archivar proyecto."""
        body = _fields(name=name, aspect_ratio=aspect_ratio, archived=archived)
        if not body:
            raise ToolError("Indica al menos un cambio.")
        return request("PATCH", f"projects/{_id(project_id)}", body)

    @server.tool(annotations=write)
    def create_studio_chapter(project_id: str, title: str,
                               script_md: str = "", continuity_md: str = "") -> dict:
        """Crear capítulo vacío o con guion y continuidad, sin iniciar GPU."""
        return request("POST", f"projects/{_id(project_id)}/chapters",
                       {"title": title, "script_md": script_md, "continuity_md": continuity_md})

    @server.tool(annotations=write)
    def update_studio_chapter(chapter_id: str, expected_revision: int, title: str | None = None,
                               script_md: str | None = None, continuity_md: str | None = None,
                               archived: bool | None = None) -> dict:
        """Actualizar capítulo con control de revisiones; archivar sin borrar escenas."""
        body = {"expected_revision": expected_revision,
                **_fields(title=title, script_md=script_md,
                          continuity_md=continuity_md, archived=archived)}
        if len(body) == 1:
            raise ToolError("Indica un cambio.")
        return request("PATCH", f"chapters/{_id(chapter_id)}", body)

    @server.tool(annotations=write)
    def create_studio_scene(chapter_id: str, title: str, description: str = "",
                             image_prompt: str = "", animation_prompt: str = "",
                             duration_seconds: float = 5.0,
                             character_ids: list[str] | None = None) -> dict:
        """Crear una escena con prompts de imagen y animación, reparto y segundos."""
        return request("POST", f"chapters/{_id(chapter_id)}/scenes", {
            "title": title, "description": description, "prompt": animation_prompt,
            "duration_seconds": duration_seconds,
            "parameters": {"image_prompt": image_prompt, "character_ids": character_ids or []},
        })

    @server.tool(annotations=write)
    def update_studio_scene(scene_id: str, expected_revision: int, title: str | None = None,
                             description: str | None = None, animation_prompt: str | None = None,
                             duration_seconds: float | None = None) -> dict:
        """Editar título, descripción, prompt H3 o tiempo sin alterar otros campos."""
        body = {"expected_revision": expected_revision,
                **_fields(title=title, description=description, prompt=animation_prompt,
                          duration_seconds=duration_seconds)}
        if len(body) == 1:
            raise ToolError("Indica un cambio.")
        return request("PATCH", f"scenes/{_id(scene_id)}", body)

    @server.tool(annotations=write)
    def set_studio_scene_frame(scene_id: str, expected_revision: int,
                                role: Literal["start", "end"], asset_id: str | None) -> dict:
        """Colocar/quitar una imagen inicial o final seleccionada, conservando versiones."""
        field = "start_asset_id" if role == "start" else "end_asset_id"
        return request("PATCH", f"scenes/{_id(scene_id)}", {
            "expected_revision": expected_revision, field: asset_id,
        })

    @server.tool(annotations=write)
    def duplicate_studio_scene(scene_id: str) -> dict:
        """Duplicar una escena con sus datos y referencias."""
        return request("POST", f"scenes/{_id(scene_id)}/duplicate")

    @server.tool(annotations=write)
    def reorder_studio_scenes(chapter_id: str, scene_ids: list[str]) -> list[dict]:
        """Reordenar todas las escenas del capítulo; backend rechaza IDs parciales."""
        return request("PUT", f"chapters/{_id(chapter_id)}/scene-order", {"scene_ids": scene_ids})

    @server.tool(annotations=dangerous)
    def delete_studio_scene(scene_id: str, confirmed: bool = False) -> dict:
        """Eliminar escena y sus versiones SOLO con confirmación explícita."""
        _confirm(confirmed)
        request("DELETE", f"scenes/{_id(scene_id)}")
        return {"deleted_scene_id": scene_id}

    @server.tool(annotations=dangerous)
    def delete_empty_studio_chapter(chapter_id: str, confirmed: bool = False) -> dict:
        """Eliminar solamente un capítulo vacío; requiere confirmación explícita."""
        _confirm(confirmed)
        request("DELETE", f"chapters/{_id(chapter_id)}")
        return {"deleted_chapter_id": chapter_id}

    @server.tool(annotations=read)
    def list_studio_scene_revisions(scene_id: str) -> list[dict]:
        """Inspeccionar historial de prompts, imágenes y duración sin modificarlo."""
        return request("GET", f"scenes/{_id(scene_id)}/revisions")

    @server.tool(annotations=write)
    def create_studio_character(project_id: str, name: str, reference_asset_id: str,
                                 description: str = "", voice_description: str = "",
                                 voice_asset_id: str | None = None) -> dict:
        """Crear personaje a partir de imagen/voz ya subidas a la biblioteca."""
        return request("POST", f"projects/{_id(project_id)}/characters", {
            "name": name, "description": description, "reference_asset_id": reference_asset_id,
            "voice_description": voice_description, "voice_asset_id": voice_asset_id,
        })

    @server.tool(annotations=write)
    def update_studio_character(project_id: str, character_id: str, expected_revision: int,
                                 name: str | None = None, description: str | None = None,
                                 reference_asset_id: str | None = None,
                                 voice_description: str | None = None,
                                 voice_asset_id: str | None = None,
                                 clear_voice: bool = False,
                                 archived: bool | None = None) -> dict:
        """Actualizar personaje, referencia o voz por asset ID; respeta la revisión."""
        characters = request("GET", f"projects/{_id(project_id)}/characters")
        current = next((c for c in characters if c["id"] == character_id), None)
        if not current:
            raise ToolError("El personaje no pertenece a este proyecto.")
        return request("PUT", f"characters/{_id(character_id)}", {
            "expected_revision": expected_revision,
            "name": name if name is not None else current["name"],
            "description": description if description is not None else current["description"],
            "reference_asset_id": reference_asset_id or current["reference_asset"]["id"],
            "voice_description": voice_description if voice_description is not None else current.get("voice_description", ""),
            "voice_asset_id": None if clear_voice else voice_asset_id if voice_asset_id is not None else (current.get("voice_asset") or {}).get("id"),
            "archived": archived if archived is not None else current["archived"],
        })

    @server.tool(annotations=read)
    def get_studio_asset(asset_id: str) -> dict:
        """Consultar el archivo por ID; inspección visual disponible en inspect_studio_image."""
        return request("GET", f"assets/{_id(asset_id)}")

    @server.tool(annotations=write)
    def request_scene_video(scene_id: str, expected_revision: int, request_id: str) -> dict:
        """Generar video H3 de una escena preparada (botón Generar esta escena); USA GPU."""
        return request("POST", f"scenes/{_id(scene_id)}/generate", {
            "expected_revision": expected_revision, "request_id": _uuid(request_id),
        })

    @server.tool(annotations=read)
    def list_scene_videos(scene_id: str) -> list[dict]:
        """Consultar todos los trabajos de video H3 y sus enlaces de resultado."""
        return request("GET", f"scenes/{_id(scene_id)}/generations")

    @server.tool(annotations=read)
    def get_studio_video_job(job_id: str) -> dict:
        """Consultar progreso y error de generación de video individual."""
        return request("GET", f"generations/{_id(job_id)}")

    @server.tool(annotations=dangerous)
    def abandon_uncertain_generation(job_id: str, confirmed: bool = False) -> dict:
        """Cerrar registro incierto; NO detiene un render ya enviado. Requiere confirmación."""
        _confirm(confirmed)
        return request("POST", f"generations/{_id(job_id)}/abandon")

    @server.tool(annotations=write)
    def request_chapter_images(chapter_id: str, request_id: str) -> dict:
        """GENERAR TODAS LAS IMÁGENES: encola las Qwen faltantes, sin iniciar video ni aprobar. USA GPU."""
        return queue_chapter_images(chapter_id, request_id, request)

    @server.tool(annotations=write)
    def generate_full_chapter(chapter_id: str, request_id: str,
                              automatic_approval: bool) -> dict:
        """BOTÓN GENERAR CAPÍTULO COMPLETO: Qwen → autoaprobación → H3 → montaje MP4. USA GPU."""
        return queue_full_chapter(chapter_id, request_id, automatic_approval, request)
