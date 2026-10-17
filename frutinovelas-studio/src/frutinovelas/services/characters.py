"""Project-scoped references. Scene revisions freeze the chosen identities and assets."""

import copy
import math

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from frutinovelas.models import Asset, Chapter, Character
from frutinovelas.schemas import AssetOut, SceneAudioGuide
from frutinovelas.services.audio import MAX_AUDIO_SECONDS


def public_character(character):
    return dict(
        id=character.id,
        project_id=character.project_id,
        name=character.name,
        description=character.description,
        voice_description=character.voice_description,
        voice_asset=(AssetOut.model_validate(character.voice_asset).model_dump() if character.voice_asset else None),
        revision=character.revision,
        archived=character.archived,
        reference_asset=AssetOut.model_validate(character.reference_asset).model_dump(),
    )


def character_rows(session, project_id, archived=False):
    return session.scalars(
        select(Character)
        .where(Character.project_id == project_id, Character.archived.is_(archived))
        .options(joinedload(Character.reference_asset), joinedload(Character.voice_asset))
        .order_by(Character.name)
    ).all()


def _guide_input(guide):
    return SceneAudioGuide.model_validate(guide).model_dump()


def validate_scene_audio(parameters, duration_seconds):
    """Use the same frame rounding as H3 and never silently trim or overlap audio."""
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("La duración de la escena no es válida.")
    guides = parameters.get("audio_guides", [])
    if not isinstance(guides, list) or len(guides) > 8:
        raise ValueError("Una escena admite como máximo ocho intervenciones de audio.")
    spans = []
    for guide in guides:
        data = _guide_input(guide)
        asset = guide.get("asset") or {}
        length = asset.get("duration_seconds")
        if (
            asset.get("kind") != "audio"
            or asset.get("id") != data["asset_id"]
            or not isinstance(length, (float, int))
            or not math.isfinite(length)
            or not 0 < length <= MAX_AUDIO_SECONDS
        ):
            raise ValueError("Una guía de audio no tiene un archivo o una duración válidos. Vuelve a seleccionarla.")
        start = round(data["start_seconds"] * 24) / 24
        end = start + length
        if end > duration_seconds + 1e-6:
            raise ValueError(
                "Una intervención de audio supera la duración de la escena. Ajusta su inicio, amplía la escena o sube un audio más corto."
            )
        spans.append((start, end))
    spans.sort()
    if any(start < previous_end - 1e-6 for (_previous_start, previous_end), (start, _end) in zip(spans, spans[1:])):
        raise ValueError("Las intervenciones de audio se superponen. Ajusta sus tiempos de inicio.")


def _audio_snapshots(session, chapter, submitted, previous):
    if not isinstance(submitted, list) or len(submitted) > 8:
        raise ValueError("Una escena admite como máximo ocho intervenciones de audio.")
    saved = [(_guide_input(guide), guide) for guide in previous]
    result = []
    for guide in submitted:
        data = _guide_input(guide)
        asset = session.get(Asset, data["asset_id"])
        if not asset or asset.kind != "audio":
            raise ValueError("Selecciona un archivo de audio válido para cada intervención.")
        # Moving an existing dialogue does not change its saved speaker identity.
        unchanged = next((snapshot for inputs, snapshot in saved if inputs == data), None)
        if unchanged is None:
            unchanged = next(
                (snapshot for inputs, snapshot in saved if all(inputs[key] == data[key] for key in ("asset_id", "character_id"))),
                None,
            )
        if unchanged is not None:
            saved_asset = unchanged.get("asset") or {}
            if (
                saved_asset.get("id") != asset.id
                or saved_asset.get("sha256") != asset.sha256
                or saved_asset.get("duration_seconds") != asset.duration_seconds
            ):
                raise ValueError("El archivo de una guía guardada cambió. Vuelve a seleccionarlo.")
            snapshot = copy.deepcopy(unchanged)
            snapshot.update(data)
            result.append(snapshot)
            continue
        character = session.get(Character, data["character_id"]) if data["character_id"] else None
        if data["character_id"] and (
            not character or character.archived or character.project_id != chapter.project_id
        ):
            raise ValueError("El personaje de una voz no pertenece a este proyecto o está archivado.")
        result.append(
            dict(
                **data,
                asset=AssetOut.model_validate(asset).model_dump(mode="json"),
                character_name=character.name if character else None,
                voice_description=character.voice_description if character else "",
            )
        )
    return result


def scene_parameters(session, chapter_id, submitted, previous=None, duration_seconds=5.0):
    """Never trust client-provided cast snapshots; unchanged selections retain their saved assets."""
    result = copy.deepcopy(submitted)
    previous = previous or {}
    ids = result.get("character_ids", [])
    if len(ids) > 2 or len(set(ids)) != len(ids):
        raise ValueError("Selecciona como máximo dos personajes distintos para este flujo Qwen.")
    if ids == previous.get("character_ids", []) and "cast" in previous:
        result["cast"] = copy.deepcopy(previous["cast"])
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise ValueError("Capítulo no encontrado.")
    if ids != previous.get("character_ids", []) or "cast" not in previous:
        cast = []
        for id in ids:
            character = session.get(Character, id)
            if not character or character.archived or character.project_id != chapter.project_id:
                raise ValueError("Un personaje no pertenece a este proyecto o está archivado.")
            asset = session.get(Asset, character.reference_asset_id)
            if not asset or asset.kind != "image":
                raise ValueError("Falta una imagen de referencia válida de un personaje.")
            cast.append(
                dict(
                    character_id=id,
                    name=character.name,
                    description=character.description,
                    asset_id=asset.id,
                    sha256=asset.sha256,
                    voice_description=character.voice_description,
                    voice_asset_id=character.voice_asset_id,
                )
            )
        result["cast"] = cast
    if "audio_guides" in result:
        result["audio_guides"] = _audio_snapshots(
            session, chapter, result["audio_guides"], previous.get("audio_guides", [])
        )
    validate_scene_audio(result, duration_seconds)
    return result
