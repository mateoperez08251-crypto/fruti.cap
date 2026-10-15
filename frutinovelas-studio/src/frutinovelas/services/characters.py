"""Project-scoped references. Scene revisions freeze the chosen identities and assets."""

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from frutinovelas.models import Asset, Chapter, Character
from frutinovelas.schemas import AssetOut


def public_character(character):
    return dict(
        id=character.id,
        project_id=character.project_id,
        name=character.name,
        description=character.description,
        revision=character.revision,
        archived=character.archived,
        reference_asset=AssetOut.model_validate(character.reference_asset).model_dump(),
    )


def character_rows(session, project_id, archived=False):
    return session.scalars(
        select(Character)
        .where(Character.project_id == project_id, Character.archived.is_(archived))
        .options(joinedload(Character.reference_asset))
        .order_by(Character.name)
    ).all()


def scene_parameters(session, chapter_id, submitted, previous=None):
    """Never trust client-provided cast snapshots; unchanged selections retain their saved assets."""
    result = dict(submitted)
    previous = previous or {}
    ids = result.get("character_ids", [])
    if len(ids) > 2 or len(set(ids)) != len(ids):
        raise ValueError("Selecciona como máximo dos personajes distintos para este flujo Qwen.")
    if ids == previous.get("character_ids", []) and "cast" in previous:
        result["cast"] = previous["cast"]
        return result
    chapter = session.get(Chapter, chapter_id)
    cast = []
    for id in ids:
        character = session.get(Character, id)
        if not character or character.archived or character.project_id != chapter.project_id:
            raise ValueError("Un personaje no pertenece a este proyecto o está archivado.")
        asset = session.get(Asset, character.reference_asset_id)
        if not asset:
            raise ValueError("Falta la referencia de un personaje.")
        cast.append(
            dict(
                character_id=id,
                name=character.name,
                description=character.description,
                asset_id=asset.id,
                sha256=asset.sha256,
            )
        )
    result["cast"] = cast
    return result
