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
from frutinovelas.db import get_session, session_factory
from frutinovelas.models import ChapterRender, GenerationJob
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
        from frutinovelas.services.queue_recovery import recover_available
        recover_available(client_factory=ComfyClient)
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


@router.post("/chapter-renders/{id}/stop")
def stop_render(id: str):
    """Stop this pipeline and its own active children; never delete finished assets."""
    from frutinovelas.services.generation import ACTIVE
    from frutinovelas.services.queue_control import stop_job
    from frutinovelas.worker import WorkerLock

    lock = WorkerLock(get_settings().resolved_data_dir / "generation_worker.lock")
    if not lock.acquire():
        raise HTTPException(409, "El worker está procesando un trabajo. Reintenta en unos segundos.")
    try:
        with session_factory()() as session:
            run = session.get(ChapterRender, id)
            if not run:
                raise HTTPException(404, "Capítulo automático no encontrado.")
            if run.state == "completed":
                return {"stopped": False, "pending_jobs": []}
            ids = {entry.get(field) for entry in run.snapshot.get("scenes", [])
                   for field in ("image_job_id", "video_job_id")}
            active = list(session.scalars(select(GenerationJob.id).where(
                GenerationJob.id.in_(ids), GenerationJob.state.in_(ACTIVE))))
            run.state, run.active_chapter_id = "failed", None
            run.error = "Proceso detenido por el usuario. Se conservan los prompts y los resultados."
            session.commit()
        pending = []
        for job_id in active:
            try:
                result = stop_job(job_id, client_factory=ComfyClient)
                if result["state"] != "cancelled":
                    pending.append(job_id)
            except (ComfyError, httpx.HTTPError, ValueError):
                # Do not free an uncertain or still-running child to permit duplicates.
                pending.append(job_id)
        return {"stopped": True, "pending_jobs": pending}
    finally:
        lock.release()
