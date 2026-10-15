"""Conexión autenticada y generación de una escena guardada."""

from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from frutinovelas.config import get_settings
from frutinovelas.db import get_session, session_factory
from frutinovelas.models import ComfyConnection, GenerationJob
from frutinovelas.services import generation as svc
from frutinovelas.services import scenes
from frutinovelas.services.comfy import ComfyClient, ComfyError, cipher, validate_url

router = APIRouter(tags=["generación"])


class ConnectionInput(BaseModel):
    url: str = Field(max_length=500)
    token: SecretStr | None = None


class GenerateInput(BaseModel):
    expected_revision: int = Field(ge=1)
    request_id: UUID


@router.get("/comfy/connection")
def get_connection(session: Session = Depends(get_session)):
    return svc.connection_public(session.get(ComfyConnection, "default"), get_settings().comfyui_base_url)


@router.put("/comfy/connection")
def save_connection(body: ConnectionInput, session: Session = Depends(get_session)):
    existing = session.get(ComfyConnection, "default")
    try:
        url = validate_url(body.url)
        token = body.token.get_secret_value().strip() if body.token else ""
        if not token and existing and existing.url == url:
            token = svc.connection_token(existing)
        if len(token) < 16:
            raise ComfyError("Pega el token completo del gateway (al menos 16 caracteres).")
        # Release the read transaction before making remote requests.
        session.rollback()
        client = ComfyClient(url, token)
        try:
            _, identity, graph = client.connect()
        finally:
            client.close()
        encrypted = cipher().encrypt(token.encode()).decode()
    except (ComfyError, httpx.HTTPError, ValueError) as exc:
        detail = (
            str(exc)
            if isinstance(exc, ComfyError)
            else "No se pudo comprobar RunPod. Revisa la URL y que el gateway esté activo."
        )
        raise HTTPException(422, detail) from exc
    existing = session.get(ComfyConnection, "default")
    if existing:
        existing.url = url
        existing.encrypted_token = encrypted
        existing.identity = identity
        existing.workflow = graph
    else:
        session.add(
            ComfyConnection(
                id="default", url=url, encrypted_token=encrypted, identity=identity, workflow=graph
            )
        )
    session.commit()
    return get_connection(session)


@router.post("/scenes/{scene_id}/generate", status_code=202)
def generate_scene(scene_id: str, body: GenerateInput, session: Session = Depends(get_session)):
    try:
        job = svc.enqueue(session, scene_id, body.expected_revision, str(body.request_id))
    except scenes.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except scenes.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ComfyError as exc:
        raise HTTPException(422, str(exc)) from exc
    return svc.public_job(job)


@router.get("/scenes/{scene_id}/generations")
def scene_generations(scene_id: str, session: Session = Depends(get_session)):
    try:
        scenes.load_scene(session, scene_id)
    except scenes.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    jobs = session.scalars(
        select(GenerationJob)
        .where(GenerationJob.scene_id == scene_id)
        .order_by(GenerationJob.created_at.desc())
    )
    return [svc.public_job(j) for j in jobs]


def _job(session, id):
    job = session.get(GenerationJob, id)
    if job is None:
        raise HTTPException(404, "Generación no encontrada.")
    return job


@router.get("/generations/{job_id}")
def generation_status(job_id: str, session: Session = Depends(get_session)):
    return svc.public_job(_job(session, job_id))


@router.post("/generations/{job_id}/abandon")
def abandon(job_id: str, session: Session = Depends(get_session)):
    job = _job(session, job_id)
    if job.state not in ("queued", "unknown"):
        raise HTTPException(409, "Solo puedes cerrar un trabajo sin enviar o de recepción incierta.")
    id = job.id
    expected_state = job.state
    session.rollback()
    changed = svc.transition(
        session_factory(),
        id,
        "failed",
        "Cerrado por el usuario; no se interrumpió la cola remota.",
        expected_states=(expected_state,),
    )
    if not changed:
        raise HTTPException(409, "El trabajo cambió de estado. Actualiza antes de volver a cerrarlo.")
    session.expire_all()
    return svc.public_job(_job(session, id))


@router.get("/generations/{job_id}/content")
def generation_content(job_id: str, download: bool = Query(False), session: Session = Depends(get_session)):
    job = _job(session, job_id)
    if job.state != "completed" or not job.result_path:
        raise HTTPException(404, "El video aún no está disponible.")
    base = get_settings().resolved_data_dir
    path = (base / job.result_path).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(404, "El archivo no está disponible en el almacenamiento.")
    return FileResponse(path, media_type=job.result_mime, filename=path.name if download else None)
