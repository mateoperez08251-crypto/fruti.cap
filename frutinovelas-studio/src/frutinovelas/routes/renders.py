"""Chapter automation is explicitly opt-in for each run; manual review remains default."""

from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from frutinovelas.config import get_settings
from frutinovelas.db import get_session
from frutinovelas.models import ChapterRender
from frutinovelas.services.chapter_render import create_run, public_run
from frutinovelas.services.comfy import ComfyClient, ComfyError

router = APIRouter(tags=["capítulos automáticos"])


class RenderRequest(BaseModel):
    request_id: UUID
    expected_revision: int = Field(ge=1)
    scene_revisions: dict[str, int] = Field(min_length=1, max_length=60)
    automatic_approval: Literal[True]


@router.post("/chapters/{chapter_id}/render", status_code=202)
def start_render(chapter_id: str, body: RenderRequest, session: Session = Depends(get_session)):
    try:
        return public_run(
            create_run(
                session,
                chapter_id,
                body.expected_revision,
                body.scene_revisions,
                str(body.request_id),
                ComfyClient,
            )
        )
    except (ComfyError, ValueError, httpx.HTTPError) as exc:
        raise HTTPException(
            422,
            str(exc)
            if not isinstance(exc, httpx.HTTPError)
            else "No se pudo comprobar RunPod; no se inició el capítulo.",
        ) from exc


@router.get("/chapters/{chapter_id}/renders")
def list_renders(chapter_id: str, session: Session = Depends(get_session)):
    return [
        public_run(r)
        for r in session.scalars(
            select(ChapterRender)
            .where(ChapterRender.chapter_id == chapter_id)
            .order_by(ChapterRender.created_at.desc())
        )
    ]


@router.get("/chapter-renders/{id}/content")
def render_content(id: str, session: Session = Depends(get_session)):
    run = session.get(ChapterRender, id)
    if not run or not run.result_path or run.state != "completed":
        raise HTTPException(404, "El capítulo aún no está disponible.")
    base = get_settings().resolved_data_dir
    path = (base / run.result_path).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(404, "El archivo del capítulo no está disponible.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)
