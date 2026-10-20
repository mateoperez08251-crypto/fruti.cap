"""Recover durable reservations without replaying prompts or mutating scene data.

All callers hold the worker OS lock. A timeout, partial queue or malformed history
is never evidence that a remote job disappeared. Recovery only writes job/run
status; it never sends interrupt, delete, upload or prompt requests.
"""
from sqlalchemy import select, update

from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.models import ChapterRender, ComfyConnection, GenerationJob, utcnow
from frutinovelas.services.comfy import ComfyClient, ComfyError, identity_key
from frutinovelas.services.generation import ACTIVE
from frutinovelas.services.queue_control import (
    GHOST_MIN_AGE_SECONDS,
    _age_seconds,
    _client,
    _error_info,
    _history_state,
    queue_ids,
)


def _change_job(factory, job, connection, **values):
    """Compare-and-swap both the inspected job and the saved connection."""
    with factory() as session:
        result = session.execute(
            update(GenerationJob).where(
                GenerationJob.id == job.id, GenerationJob.state == job.state,
                GenerationJob.updated_at == job.updated_at,
                select(ComfyConnection.id).where(
                    ComfyConnection.id == "default", ComfyConnection.url == connection.url,
                    ComfyConnection.identity == connection.identity,
                ).exists(),
            ).values(updated_at=utcnow(), **values)
        )
        session.commit()
        return bool(result.rowcount)


def _recover_runs(factory, connection):
    with factory() as session:
        current = session.get(ComfyConnection, "default")
        if not current or current.url != connection.url or current.identity != connection.identity:
            return
        for run in session.scalars(select(ChapterRender).where(ChapterRender.active_chapter_id.is_not(None))):
            ids = {entry.get(field) for entry in run.snapshot.get("scenes", [])
                   for field in ("image_job_id", "video_job_id")}
            states = list(session.scalars(select(GenerationJob.state).where(GenerationJob.id.in_(ids))))
            interrupted = any(state in ("cancelled", "failed") for state in states)
            historical = (run.snapshot.get("url") != connection.url
                          or run.snapshot.get("runtime_key") != identity_key(connection.identity or {}))
            if interrupted or (historical and not any(state in ACTIVE for state in states)):
                run.state, run.active_chapter_id = "failed", None
                run.error = "Una generación fue interrumpida. Puedes reintentar; los prompts y resultados se conservan."
        session.commit()


def recover_available(factory=None, client_factory=None):
    """Best effort, also safe with a separate worker process or concurrent API calls."""
    from frutinovelas.worker import WorkerLock

    lock = WorkerLock(get_settings().resolved_data_dir / "generation_worker.lock")
    if not lock.acquire():
        return {"status": "busy", "recovered": []}
    try:
        return recover_locked(factory or session_factory(), client_factory or ComfyClient)
    finally:
        lock.release()


def recover_locked(factory, client_factory):
    """Called only between worker operations, never during an in-flight POST."""
    import httpx

    with factory() as session:
        connection = session.get(ComfyConnection, "default")
        jobs = list(session.scalars(select(GenerationJob).where(GenerationJob.state.in_(ACTIVE))))
        run = session.scalar(select(ChapterRender.id).where(ChapterRender.active_chapter_id.is_not(None)).limit(1))
        if not connection or (not jobs and not run):
            return {"status": "idle", "recovered": []}
        session.expunge_all()
    recovered = []
    client = None
    try:
        client = _client(connection, client_factory)
        key = identity_key(connection.identity or {})
        if identity_key(client.get("/frutinovelas/identity")) != key:
            return {"status": "connection_changed", "recovered": []}
        first = set(sum(queue_ids(client.get("/queue")), []))
        for job in jobs:
            snap = job.snapshot or {}
            historical = snap.get("url") != connection.url or identity_key(snap.get("identity") or {}) != key
            message = None
            if historical:
                # A changed tunnel URL alone does not prove a different runtime.
                # Preserve work/results visible on the new connection.
                found = job.prompt_id in first or _history_state(client, job.prompt_id) != "not_found"
                if found:
                    if identity_key(snap.get("identity") or {}) == key:
                        _change_job(factory, job, connection,
                                    snapshot={**snap, "url": connection.url},
                                    encrypted_token=connection.encrypted_token)
                    continue
                message = ("Registro de una conexión anterior liberado automáticamente. "
                           "No se canceló trabajo remoto ni se modificaron prompts o resultados.")
            elif job.state not in ("queued", "uploading") and job.prompt_id not in first:
                # Grace is measured from the last transition, not creation: a job
                # may have waited hours locally before a recent uncertain submission.
                if _age_seconds(job.updated_at) < GHOST_MIN_AGE_SECONDS:
                    continue
                if _history_state(client, job.prompt_id) != "not_found":
                    continue
                second = set(sum(queue_ids(client.get("/queue")), []))
                if job.prompt_id in second:
                    continue
                # A pending prompt may finish between the history and queue reads.
                if _history_state(client, job.prompt_id) != "not_found":
                    continue
                message = "Generación ausente de cola e historial; registro liberado sin reenviar ni interrumpir."
            if message:
                if _change_job(factory, job, connection, state="cancelled", error=message, active_scene_id=None):
                    recovered.append(job.id)
        _recover_runs(factory, connection)
        return {"status": "ok", "recovered": recovered}
    except (ComfyError, httpx.HTTPError, ValueError, OSError) as exc:
        if recovered:
            _recover_runs(factory, connection)
        return {"status": "unverified", "recovered": recovered, "diagnostic": _error_info(exc)}
    finally:
        if client:
            client.close()
