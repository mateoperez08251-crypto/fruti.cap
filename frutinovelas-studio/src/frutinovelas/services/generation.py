"""Una generación captura una revisión y nunca modifica su prompt ni sus referencias."""

from __future__ import annotations

import copy
import secrets

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from frutinovelas.models import ComfyConnection, GenerationJob, utcnow
from frutinovelas.services import scenes
from frutinovelas.services.comfy import ComfyError, cipher

ACTIVE = ("queued", "uploading", "submitting", "waiting", "running", "downloading", "unknown")


def enqueue(session, scene_id, expected_revision, request_id):
    scene = scenes.load_scene(session, scene_id)
    existing = session.get(GenerationJob, request_id)
    if existing:
        if existing.scene_id != scene_id:
            raise ComfyError("El ID de petición pertenece a otra escena.")
        if existing.snapshot["scene_revision"] != expected_revision:
            raise ComfyError("El ID de petición pertenece a otra revisión de la escena.")
        # A retry refers to the saved snapshot even if the scene has since changed.
        return existing
    if scene.revision != expected_revision:
        raise scenes.Conflict(scene.revision)
    existing = session.scalar(select(GenerationJob).where(GenerationJob.active_scene_id == scene_id))
    if existing:
        return existing
    rev = scene.current
    if not rev or not rev.prompt.strip() or not rev.start_asset_id:
        raise ComfyError("Guarda el prompt y una imagen inicial antes de generar.")
    if not 4 <= rev.duration_seconds <= 15:
        raise ComfyError("Este perfil H3 admite entre 4 y 15 segundos. Usa 5 segundos para la prueba.")
    connection = session.get(ComfyConnection, "default")
    if connection is None:
        raise ComfyError("Configura y comprueba la conexión con RunPod en «Conexión ComfyUI».")
    params = rev.parameters or {}
    seed = params.get("seed") if params.get("seed_mode") == "fixed" else secrets.randbelow(2**53)
    if type(seed) is not int or not 0 <= seed < 2**53:
        raise ComfyError("La semilla debe ser un entero entre 0 y 9007199254740991.")
    snapshot = dict(
        revision_number=rev.number,
        scene_revision=scene.revision,
        prompt=rev.prompt,
        start_asset_id=rev.start_asset_id,
        end_asset_id=rev.end_asset_id,
        duration=rev.duration_seconds,
        seed=seed,
        url=connection.url,
        identity=copy.deepcopy(connection.identity),
        graph=copy.deepcopy(connection.workflow),
    )
    job = GenerationJob(
        id=request_id,
        prompt_id=request_id,
        scene_id=scene_id,
        active_scene_id=scene_id,
        state="queued",
        snapshot=snapshot,
        encrypted_token=connection.encrypted_token,
    )
    try:
        session.add(job)
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.get(GenerationJob, request_id)
        if existing:
            if existing.scene_id != scene_id or existing.snapshot["scene_revision"] != expected_revision:
                raise ComfyError("El ID de petición pertenece a otra escena o revisión.") from None
            return existing
        existing = session.scalar(select(GenerationJob).where(GenerationJob.active_scene_id == scene_id))
        if existing:
            return existing
        raise
    return job


def public_job(job):
    # Do not serialize the snapshot or encrypted credentials to a browser/MCP client.
    return _public_job(
        id=job.id,
        scene_id=job.scene_id,
        state=job.state,
        error=job.error,
        revision_number=job.snapshot["revision_number"],
        duration=job.snapshot["duration"],
        seed=job.snapshot["seed"],
        created_at=job.created_at,
        updated_at=job.updated_at,
        result_path=job.result_path,
    )


def list_public_jobs(session, scene_id):
    # Polling needs only these three snapshot values, never the workflow, prompt or token.
    rows = session.execute(
        select(
            GenerationJob.id,
            GenerationJob.scene_id,
            GenerationJob.state,
            GenerationJob.error,
            GenerationJob.created_at,
            GenerationJob.updated_at,
            GenerationJob.result_path,
            GenerationJob.snapshot["revision_number"].as_integer().label("revision_number"),
            GenerationJob.snapshot["duration"].as_float().label("duration"),
            GenerationJob.snapshot["seed"].as_integer().label("seed"),
        )
        .where(GenerationJob.scene_id == scene_id)
        .order_by(GenerationJob.created_at.desc())
    )
    return [_public_job(**row) for row in rows.mappings()]


def _public_job(
    *, id, scene_id, state, error, revision_number, duration, seed, created_at, updated_at, result_path
):
    frames = max(5, round(duration * 24))
    frames += (5 - frames % 17) % 17
    return dict(
        id=id,
        scene_id=scene_id,
        state=state,
        error=error,
        revision_number=revision_number,
        duration_seconds=duration,
        frames=frames,
        effective_seconds=frames / 24,
        seed=seed,
        created_at=created_at,
        updated_at=updated_at,
        result_url=f"/api/v1/generations/{id}/content" if result_path else None,
    )


def transition(factory, job_id, state, error="", *, expected_states=ACTIVE, **extra):
    with factory() as session:
        values = dict(state=state, error=error, updated_at=utcnow(), **extra)
        if state in ("completed", "failed"):
            values["active_scene_id"] = None
        result = session.execute(
            update(GenerationJob)
            .where(GenerationJob.id == job_id, GenerationJob.state.in_(expected_states))
            .values(**values)
        )
        session.commit()
        return bool(result.rowcount)


def connection_public(connection, fallback_url):
    return dict(
        url=connection.url if connection else fallback_url,
        configured=bool(connection),
        has_token=bool(connection),
        identity=connection.identity if connection else {},
    )


def connection_token(connection):
    return cipher().decrypt(connection.encrypted_token.encode()).decode()
