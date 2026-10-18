"""Character library: select an uploaded image and name it within its project."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from frutinovelas.db import get_session
from frutinovelas.models import Asset, Character, Project
from frutinovelas.services.characters import character_rows, public_character
from frutinovelas.services.scenes import audit

router = APIRouter(tags=["personajes"])


class CharacterInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    reference_asset_id: str
    voice_description: str = Field(default="", max_length=4000)
    voice_asset_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("name")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Escribe el nombre del personaje.")
        return value.strip()


class CharacterUpdate(CharacterInput):
    expected_revision: int = Field(ge=1)
    archived: bool = False


@router.get("/projects/{project_id}/characters")
def list_characters(project_id: str, session: Session = Depends(get_session)):
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "Proyecto no encontrado.")
    return [public_character(c) for c in character_rows(session, project_id)]


def _save(session, character, data):
    reference = session.get(Asset, data.reference_asset_id)
    if reference is None or reference.kind != "image":
        raise HTTPException(422, "Sube una imagen de referencia válida.")
    if "voice_asset_id" in data.model_fields_set:
        voice = session.get(Asset, data.voice_asset_id) if data.voice_asset_id else None
        if data.voice_asset_id and (voice is None or voice.kind != "audio"):
            raise HTTPException(422, "Selecciona un archivo de audio válido para la voz.")
        character.voice_asset_id = data.voice_asset_id
    if "voice_description" in data.model_fields_set:
        character.voice_description = data.voice_description
    character.name = data.name
    character.description = data.description
    character.reference_asset_id = data.reference_asset_id
    try:
        audit(session, "character.saved", "character", character.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "Ya existe un personaje con ese nombre en el proyecto.") from exc
    session.expire(character, ["reference_asset", "voice_asset"])
    return public_character(character)


@router.post("/projects/{project_id}/characters", status_code=201)
def create_character(project_id: str, body: CharacterInput, session: Session = Depends(get_session)):
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "Proyecto no encontrado.")
    from frutinovelas.models import new_id

    character = Character(id=new_id(), project_id=project_id)
    session.add(character)
    # Check the asset before autoflush of this incomplete row.
    with session.no_autoflush:
        return _save(session, character, body)


@router.put("/characters/{character_id}")
def update_character(character_id: str, body: CharacterUpdate, session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    if character is None:
        raise HTTPException(404, "Personaje no encontrado.")
    if character.revision != body.expected_revision:
        raise HTTPException(409, "El personaje cambió. Actualiza antes de guardar.")
    character.archived = body.archived
    character.revision += 1
    return _save(session, character, body)
