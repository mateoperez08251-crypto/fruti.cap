"""Guías versionadas: mismas fuentes para skills de repositorio y clientes MCP."""

import re
from pathlib import Path
from typing import Literal

Task = Literal["story", "image", "animation", "review"]
Preset = Literal["frutinovelas", "general"]

GUIDES = {
    "director-core": ("DIRECTOR_CORE.md", "Dirección general para cualquier sujeto o escena"),
    "preferences": ("FRUTINOVELAS_PREFERENCES.md", "Preferencias habituales de frutinovelas"),
    "visual-direction": ("VISUAL_DIRECTION.md", "Luz, sombras, actuación, física y cámara"),
    "models": ("MODEL_COMPATIBILITY.md", "Capacidades reales de los perfiles del repositorio"),
    "usage": ("PROMPT_STUDIO.md", "CLI, API, MCP y esquemas de prompts"),
    "research": ("PROMPT_RESEARCH.md", "Fuentes primarias y alcance de la investigación"),
    "chatgpt-director": ("CHATGPT_DIRECTOR.md", "Instrucciones portables para un chat"),
    "example-story": ("FRUTINOVELAS_CONTINUITY.md", "Solo el arco de la heladería: contexto opcional"),
    "skill-story": ("skills/fruti-story-continuity.md", "Procedimiento de guion y continuidad"),
    "skill-image": ("skills/fruti-image-direction.md", "Procedimiento de imagen y edición Qwen"),
    "skill-animation": ("skills/fruti-h3-animation.md", "Procedimiento de animación H3"),
    "skill-review": ("skills/fruti-prompt-review.md", "Procedimiento de revisión por evidencia"),
}
_SOURCE_DOCS = Path(__file__).resolve().parents[2] / "docs"
_BUNDLED_DOCS = Path(__file__).resolve().parent / "_prompt_guides"


def guidance_catalog() -> list[dict[str, str]]:
    return [
        {"name": key, "uri": f"frutinovelas://guides/{key}", "description": description}
        for key, (_, description) in GUIDES.items()
    ]


def read_guide(name: str) -> str:
    if name not in GUIDES:
        raise ValueError("Guía desconocida; consulta frutinovelas://guides.")
    filename, _ = GUIDES[name]
    # Development checkout and installed wheels share the same versioned Markdown.
    root = _BUNDLED_DOCS if _BUNDLED_DOCS.is_dir() else _SOURCE_DOCS
    try:
        content = (root / filename).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError("Falta una guía del paquete; reinstala desde el repositorio completo.") from exc
    for key, (source, _) in GUIDES.items():
        content = re.sub(
            r"\]\((?:\.\./)?" + re.escape(source) + r"\)",
            f"](frutinovelas://guides/{key})",
            content,
        )
    return content


def get_guidance(
    task: Task = "animation", preset: Preset = "frutinovelas", include_example_story: bool = False
) -> dict:
    if task not in ("story", "image", "animation", "review") or preset not in ("frutinovelas", "general"):
        raise ValueError("Tarea o preset desconocido.")
    if include_example_story and preset != "frutinovelas":
        raise ValueError("La historia de ejemplo pertenece al preset frutinovelas.")
    keys = ["director-core", "visual-direction", "models", f"skill-{task}"]
    if preset == "frutinovelas":
        keys.append("preferences")
    if include_example_story:
        keys.append("example-story")
    return {
        "task": task,
        "preset": preset,
        "scope": (
            "Aplicar a la escena actual. Los ejemplos ilustran técnicas; no imponen personajes ni eventos. "
            "En preset general usar los sujetos, estilo, idioma y sonido solicitados. "
            "Si se compila H3Draft, sobrescribir visual_style, language y non_diegetic_music cuando proceda; "
            "sus valores predeterminados no son decisiones creativas universales."
        ),
        "guides": [
            {"name": key, "uri": f"frutinovelas://guides/{key}", "content": read_guide(key)} for key in keys
        ],
        "usage_uri": "frutinovelas://guides/usage",
        "persistence": "Guías versionadas; no entrenan el modelo ni guardan nuevas preferencias por MCP.",
    }
