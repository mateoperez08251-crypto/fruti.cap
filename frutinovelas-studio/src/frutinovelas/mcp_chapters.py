"""MCP: creación idempotente de un capítulo completo a partir de un plan editorial.

Se sirve exclusivamente a la API local y nunca lanza generación ni aprueba imágenes.
"""
from __future__ import annotations

from typing import Callable

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, model_validator

from frutinovelas.schemas import ChapterCreate, SceneCreate, SceneParameters


class McpSceneDraft(BaseModel):
    """Escena preparada con prompt de imagen y animación, sin realizar inferencia."""
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    image_prompt: str = Field(min_length=30, max_length=30000)
    animation_prompt: str = Field(min_length=30)
    duration_seconds: float = Field(ge=4, le=15, allow_inf_nan=False)
    character_ids: list[str] = Field(default_factory=list, max_length=2)
    voice_character_ids: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def unique_cast(self):
        if len(set(self.character_ids)) != len(self.character_ids):
            raise ValueError("No se admiten personajes duplicados.")
        if len(set(self.voice_character_ids)) != len(self.voice_character_ids):
            raise ValueError("No se admiten voces duplicadas.")
        return self


class McpChapterPlan(BaseModel):
    """Plan editorial de un capítulo, con claves de escena para reintentos seguros."""
    project_id: str = Field(min_length=1)
    plan_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,39}$")
    chapter_title: str = Field(min_length=1, max_length=200)
    script_md: str = Field(min_length=1)
    continuity_md: str = Field(min_length=1)
    scenes: list[McpSceneDraft] = Field(min_length=1, max_length=60)


def scene_payload(draft: McpSceneDraft, key: str) -> dict:
    return SceneCreate(
        title=draft.title,
        description=draft.description,
        external_key=key,
        prompt=draft.animation_prompt,
        duration_seconds=draft.duration_seconds,
        parameters=SceneParameters(
            character_ids=draft.character_ids,
            image_prompt=draft.image_prompt,
            image_approval="manual",
            voice_character_ids=draft.voice_character_ids,
        ),
    ).model_dump(exclude_none=True)


def same_scene(actual: dict, expected: dict) -> bool:
    """Solo reutilizar la misma escena, nunca pisar cambios posteriores."""
    old, new = actual.get("parameters", {}), expected["parameters"]
    return (
        actual.get("external_key") == expected["external_key"]
        and actual.get("title") == expected["title"]
        and actual.get("description") == expected["description"]
        and actual.get("prompt") == expected["prompt"]
        and actual.get("duration_seconds") == expected["duration_seconds"]
        and old.get("image_prompt") == new["image_prompt"]
        and old.get("character_ids", []) == new["character_ids"]
        and old.get("voice_character_ids", []) == new["voice_character_ids"]
        and old.get("image_approval", "manual") == "manual"
        and actual.get("start_asset") is None
        and actual.get("end_asset") is None
    )


def apply_plan(plan: McpChapterPlan, request: Callable) -> dict:
    """Crear o reanudar sin sobrescribir capítulos ni escenas divergentes."""
    from urllib.parse import quote

    chapters_url = f"projects/{quote(plan.project_id, safe='')}/chapters"
    chapters = request("GET", chapters_url)
    matches = [c for c in chapters if c["title"].strip().casefold() == plan.chapter_title.strip().casefold()]
    if len(matches) > 1:
        raise ToolError("Hay varios capítulos con el mismo título; revisa Studio antes de continuar.")

    # Validar todas las referencias y duraciones antes del primer POST.
    chars = {
        c["id"]: c
        for c in request("GET", f"projects/{quote(plan.project_id, safe='')}/characters")
    }
    payloads = []
    for index, draft in enumerate(plan.scenes, 1):
        for character_id in draft.character_ids:
            character = chars.get(character_id)
            if not character or character.get("archived") or not character.get("reference_asset"):
                raise ToolError(f"Escena {index}: falta un personaje o su imagen de referencia.")
        total_audio = 0.0
        for character_id in draft.voice_character_ids:
            character = chars.get(character_id)
            audio = character.get("voice_asset") if character else None
            if not audio or character.get("archived"):
                raise ToolError(f"Escena {index}: la muestra de voz no existe.")
            seconds = audio.get("duration_seconds")
            if seconds is None or not 2 <= seconds <= 15:
                raise ToolError(f"Escena {index}: una muestra de voz debe durar entre 2 y 15 s.")
            total_audio += seconds
        if total_audio > 15.00001:
            raise ToolError(f"Escena {index}: las voces suman más de 15 s.")
        payloads.append(scene_payload(draft, f"{plan.plan_id}-{index:02d}"))

    if matches:
        chapter = request("GET", f"chapters/{quote(matches[0]['id'], safe='')}")
        if chapter["script_md"] != plan.script_md or chapter["continuity_md"] != plan.continuity_md:
            raise ToolError("El capítulo del mismo título tiene otro guion o continuidad. No se sobrescribió.")
    else:
        chapter = request("POST", chapters_url, ChapterCreate(
            title=plan.chapter_title, script_md=plan.script_md, continuity_md=plan.continuity_md,
        ).model_dump())

    chapter_id = chapter["id"]
    scenes_url = f"chapters/{quote(chapter_id, safe='')}/scenes"
    existing = request("GET", scenes_url)
    keys = [p["external_key"] for p in payloads]
    if [s.get("external_key") for s in existing] != keys[:len(existing)]:
        raise ToolError("El capítulo tiene escenas ajenas al plan o reordenadas; no se sobrescribió.")

    # Validar todas las escenas existentes ANTES de añadir cualquier escena.
    for saved, expected in zip(existing, payloads):
        if not same_scene(saved, expected):
            raise ToolError(f"La escena «{expected['title']}» ya fue editada; no se sobrescribió.")

    result = []
    for index, expected in enumerate(payloads):
        scene = existing[index] if index < len(existing) else request("POST", scenes_url, expected)
        result.append({
            "id": scene["id"],
            "title": scene["title"],
            "duration_seconds": scene["duration_seconds"],
            "revision": scene["revision"],
            "characters": len(expected["parameters"]["character_ids"]),
        })
    return {
        "chapter_id": chapter_id,
        "title": chapter["title"],
        "scenes": result,
        "total_requested_seconds": round(sum(scene["duration_seconds"] for scene in result), 2),
        "generation_started": False,
    }


def register_chapter_tools(server, write_annotations, request: Callable) -> None:
    @server.tool(annotations=write_annotations)
    def create_studio_chapter_plan(plan: McpChapterPlan) -> dict:
        """Crear capítulo, escenas, personajes, Qwen/H3 y segundos directamente en Studio; sin ejecutar GPU. Evita duplicados y no pisa cambios."""
        return apply_plan(plan, request)
