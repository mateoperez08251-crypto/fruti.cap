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
from frutinovelas.models import ComfyConnection, GenerationJob, Scene
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
    from frutinovelas.services.queue_recovery import recover_available
    recover_available(client_factory=ComfyClient)
    return get_connection(session)


@router.post("/scenes/{scene_id}/generate", status_code=202)
def generate_scene(scene_id: str, body: GenerateInput, session: Session = Depends(get_session)):
    try:
        from frutinovelas.services.queue_recovery import recover_available
        recover_available(client_factory=ComfyClient)
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
    if session.scalar(select(Scene.id).where(Scene.id == scene_id)) is None:
        raise HTTPException(404, "Escena no encontrada.")
    return svc.list_public_jobs(session, scene_id)


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
    if job.state == "unknown":
        # Compatibility endpoint: an uncertain POST is not permission to forget
        # real remote work and permit a duplicate generation.
        session.rollback()
        from frutinovelas.services.queue_control import reconcile_ghost
        try:
            reconcile_ghost(job_id, client_factory=ComfyClient)
        except (ComfyError, httpx.HTTPError, ValueError) as exc:
            raise HTTPException(409, "No se pudo verificar que el trabajo haya desaparecido. Usa Recuperar cola.") from exc
        session.expire_all()
        return svc.public_job(_job(session, job_id))
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


@router.delete("/generations/{job_id}/output")
def discard_generated_output(job_id: str, session: Session = Depends(get_session)):
    """Discard a finished, unlinked generation without modifying its history."""
    from frutinovelas.models import Asset, ChapterRender, Character, NarratedVideo, SceneRevision
    from frutinovelas.services.assets import asset_path
    job = _job(session, job_id)
    if job.state not in ("completed", "failed"):
        raise HTTPException(409, "No se pueden borrar resultados de trabajos activos.")
    if job.result_asset_id:
        asset_id = job.result_asset_id
        if session.scalar(select(SceneRevision.id).where(
            (SceneRevision.start_asset_id == asset_id) | (SceneRevision.end_asset_id == asset_id)).limit(1)):
            raise HTTPException(409, "La imagen se usa en una revisión de escena. Conserva el historial o desasigna otra imagen.")
        if session.scalar(select(Character.id).where(Character.reference_asset_id == asset_id).limit(1)):
            raise HTTPException(409, "La imagen es una referencia de personaje.")
        for video in session.scalars(select(NarratedVideo)):
            if any(shot.get("image_asset_id") == asset_id for shot in video.shots):
                raise HTTPException(409, "La imagen se utiliza en un video narrado.")
        asset = session.get(Asset, asset_id)
        if asset:
            other = session.scalar(select(GenerationJob.id).where(
                GenerationJob.result_asset_id == asset_id, GenerationJob.id != job.id).limit(1))
            if other:
                raise HTTPException(409, "La imagen se comparte con otra generación.")
    # Video results in chapter renders may be needed to reassemble archived runs.
    if job.kind == "video":
        for render in session.scalars(select(ChapterRender)):
            if any(entry.get("video_job_id") == job_id for entry in render.snapshot.get("scenes", [])):
                raise HTTPException(409, "El video pertenece al historial de un capítulo automático.")
    # Purge the generated ComfyUI copy first; otherwise keep the local file
    # so a failed remote cleanup can be retried without losing data.
    from frutinovelas.models import ComfyConnection
    from frutinovelas.services.generation import connection_token
    connection = session.get(ComfyConnection, "default")
    if connection:
        remote = ComfyClient(connection.url, connection_token(connection))
        try:
            remote.request("DELETE", f"/frutinovelas/narration/generated/{job.id}",
                           params={"kind": job.kind})
        except (ComfyError, httpx.HTTPError) as exc:
            raise HTTPException(503, "No se pudo liberar la copia remota. Actualiza el gateway o reintenta con ComfyUI conectado.") from exc
        finally:
            remote.close()
    settings = get_settings()
    filename = None
    if job.result_path:
        filename = (settings.resolved_data_dir / job.result_path).resolve()
        if settings.resolved_data_dir not in filename.parents:
            raise HTTPException(422, "Ruta inválida para eliminación.")
    if job.result_asset_id:
        asset = session.get(Asset, job.result_asset_id)
        if asset:
            session.delete(asset)
    job.result_asset_id = None
    job.result_path = None
    job.result_sha256 = None
    job.result_mime = None
    snapshot = dict(job.snapshot)
    snapshot["discarded"] = True
    job.snapshot = snapshot
    session.commit()
    if filename and filename.is_file():
        filename.unlink()
    return {"discarded": True, "remote_copy": "deleted" if connection else "not_connected", "local_output_deleted": True}


@router.get("/comfy/queue")
def comfy_queue():
    """Read only managed job IDs. Never exposes others' prompts or tokens."""
    from frutinovelas.services.queue_control import list_queue
    try:
        return list_queue()
    except (ComfyError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(422, "No se pudo consultar la cola. Comprueba el diagnóstico de conexión.") from exc


@router.post("/comfy/queue/recover")
def recover_queue():
    from frutinovelas.services.queue_recovery import recover_available
    return recover_available(client_factory=ComfyClient)


@router.post("/generations/{job_id}/stop")
def stop_generation(job_id: str):
    """Stop one managed generation only, preserving history and other jobs."""
    from frutinovelas.services.queue_control import stop_job
    try:
        return stop_job(job_id)
    except (ComfyError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ComfyError) else "No se pudo detener el trabajo remoto.") from exc

@router.post("/generations/{job_id}/reconcile")
def reconcile_ghost_generation(job_id: str, detach_old_runtime: bool = False):
    """Explicitly reconcile a stale local record, never interrupt remote work."""
    from frutinovelas.services.queue_control import reconcile_ghost
    try:
        return reconcile_ghost(job_id, detach_old_runtime=detach_old_runtime)
    except (ComfyError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ComfyError) else "No se pudo verificar el runtime.") from exc


@router.post("/comfy/queue/pending/{prompt_id}/remove")
def remove_pending_ghost(prompt_id: str):
    """Delete one confirmed untracked remote pending prompt, never all or running."""
    from frutinovelas.services.queue_control import remove_untracked_pending
    try:
        return remove_untracked_pending(prompt_id)
    except (ComfyError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ComfyError) else "No se pudo comprobar la cola.") from exc
