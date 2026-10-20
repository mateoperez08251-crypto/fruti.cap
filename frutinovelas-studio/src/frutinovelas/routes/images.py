"""Explicit image generation and approval. No automatic attachment to video inputs."""

from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from frutinovelas.db import get_session
from frutinovelas.models import Scene
from frutinovelas.services import scenes
from frutinovelas.services.comfy import ComfyClient, ComfyError
from frutinovelas.services.image_generation import attach_image, enqueue_image, public_image_job

router = APIRouter(tags=["imágenes de escenas"])


class ImageRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    request_id: UUID
    auto_animate: bool = False


class ImageApproval(BaseModel):
    expected_revision: int = Field(ge=1)
    role: Literal["start", "end"] = "start"


def _error(exc):
    return HTTPException(
        404 if isinstance(exc, scenes.NotFound) else 409 if isinstance(exc, scenes.Conflict) else 422,
        str(exc)
        if not isinstance(exc, httpx.HTTPError)
        else "No se pudo comprobar Qwen. Revisa la conexión con RunPod.",
    )


@router.post("/scenes/{scene_id}/generate-image", status_code=202)
def generate_image(scene_id: str, body: ImageRequest, session: Session = Depends(get_session)):
    try:
        from frutinovelas.services.queue_recovery import recover_available
        recover_available(client_factory=ComfyClient)
        return public_image_job(
            enqueue_image(
                session,
                scene_id,
                body.expected_revision,
                str(body.request_id),
                ComfyClient,
                auto_animate=body.auto_animate,
            )
        )
    except (scenes.NotFound, scenes.Conflict, ComfyError, httpx.HTTPError, ValueError) as exc:
        raise _error(exc) from exc


@router.get("/scenes/{scene_id}/image-generations")
def image_jobs(scene_id: str, session: Session = Depends(get_session)):
    if session.scalar(select(Scene.id).where(Scene.id == scene_id)) is None:
        raise HTTPException(404, "Escena no encontrada.")
    from frutinovelas.services.image_generation import list_image_jobs

    return list_image_jobs(session, scene_id)


@router.post("/image-generations/{job_id}/approve")
def approve_image(job_id: str, body: ImageApproval, session: Session = Depends(get_session)):
    try:
        return attach_image(session, job_id, body.expected_revision, body.role)
    except (scenes.NotFound, scenes.Conflict, scenes.Invalid, ComfyError) as exc:
        raise _error(exc) from exc
