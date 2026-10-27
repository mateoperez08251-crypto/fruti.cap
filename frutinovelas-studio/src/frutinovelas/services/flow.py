"""Persistent Flow orchestration, isolated from the ComfyUI worker."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from contextlib import contextmanager
from uuid import UUID, uuid5

from sqlalchemy import select

from frutinovelas.config import get_settings
from frutinovelas.models import Asset, Chapter, FlowBatch, FlowConnection, FlowJob, Project, utcnow
from frutinovelas.schemas import SceneUpdate
from frutinovelas.services import scenes
from frutinovelas.services.assets import asset_path
from frutinovelas.services.flow_media import digest_file, store_result, verified_path
from frutinovelas.services.flow_transport import FlowError, flow_dir

TERMINAL = ("completed", "failed", "cancelled")
REMOTE = ("submitting", "running", "unknown", "blocked", "cancel_requested", "downloading")


@contextmanager
def operation_lock():
    from frutinovelas.worker import WorkerLock
    lock = WorkerLock(flow_dir() / "studio.lock")
    if not lock.acquire():
        raise FlowError("Flow está procesando otra operación. Reintenta en unos segundos.")
    try:
        yield
    finally:
        lock.release()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def public_job(job, *, details=False):
    result = {key: getattr(job, key) for key in (
        "id", "batch_id", "project_id", "chapter_id", "scene_id", "position", "kind", "state", "approval",
        "cancel_requested", "remote_stopped", "error", "result_asset_id", "result_sha256",
        "result_metadata", "created_at", "updated_at", "dependency_id")}
    result.update(provider="flow", title=job.snapshot["title"],
                  scene_revision=job.snapshot["scene_revision"],
                  result_url=f"/api/v1/flow/jobs/{job.id}/content" if job.result_path else None,
                  requested_duration=job.snapshot.get("duration_seconds"))
    if details:
        result["snapshot"] = job.snapshot
    return result


def jobs_for_batch(session, batch_id):
    return list(session.scalars(select(FlowJob).where(FlowJob.batch_id == batch_id).order_by(FlowJob.position)))


def get_job(session, job_id):
    job = session.get(FlowJob, job_id)
    if job is None:
        raise scenes.NotFound("Trabajo Flow no encontrado.")
    return job


def change(session, job, state, error="", **values):
    previous = job.state
    job.state, job.error, job.updated_at = state, error, utcnow()
    for key, value in values.items():
        setattr(job, key, value)
    if state in TERMINAL:
        job.active_key = None
    if previous != state:
        scenes.audit(session, "flow.state", "flow_job", job.id, previous=previous, state=state)


def _reference(session, asset_id):
    asset = session.get(Asset, asset_id)
    if asset is None or asset.kind != "image":
        raise FlowError("Falta una imagen de referencia registrada.")
    path = asset_path(get_settings(), asset)
    if not path.is_file() or digest_file(path) != asset.sha256:
        raise FlowError("Una referencia falta o cambió. Recupera su archivo original.")
    return {"asset_id": asset.id, "sha256": asset.sha256}


def enqueue_plan(session, plan, commit=True, project_key=None):
    """Queue Flow jobs. ``project_key`` names the story: same key, same Flow project."""
    spec = plan.model_dump(mode="json")
    fid = fingerprint(spec)
    request_id = str(plan.request_id)
    prior = session.get(FlowBatch, request_id)
    if prior:
        if prior.fingerprint != fid:
            raise FlowError("request_id ya pertenece a otra solicitud. No se modificó el trabajo original.")
        return jobs_for_batch(session, request_id)
    project = session.get(Project, str(plan.project_id))
    chapter = session.get(Chapter, str(plan.chapter_id))
    if not project or not chapter or chapter.project_id != project.id:
        raise FlowError("El capítulo no pertenece al proyecto indicado.")
    if project.archived or chapter.archived:
        raise FlowError("El proyecto o capítulo está archivado.")
    connection = session.get(FlowConnection, "default")
    if not connection or not connection.connected:
        raise FlowError("Conecta Flow Automation antes de encolar.")
    requested = {str(k): v for k, v in plan.scene_revisions.items()}
    if any(v < 1 for v in requested.values()):
        raise FlowError("Revisión inválida.")
    if set(map(str, plan.prompts)) - requested.keys() or set(map(str, plan.video_prompts)) - requested.keys():
        raise FlowError("Los prompts incluyen escenas fuera de la selección.")
    ordered = [s for s in scenes.list_scenes(session, chapter.id) if s.id in requested]
    if len(ordered) != len(requested):
        raise FlowError("Una escena no pertenece a este capítulo.")
    output = []
    for scene in ordered:
        if scene.revision != requested[scene.id]:
            raise scenes.Conflict(scene.revision)
        rev = scene.current
        if rev is None:
            raise FlowError("La escena no tiene una revisión guardada.")
        kinds = ("image", "video") if plan.generation_mode == "image_video" else (plan.generation_mode,)
        image_id = str(uuid5(plan.request_id, scene.id + ":image"))
        for kind in kinds:
            if session.scalar(select(FlowJob.id).where(FlowJob.active_key == scene.id + ":" + kind)):
                raise FlowError(f"«{scene.title}» ya tiene un trabajo Flow activo de este tipo.")
            overrides = plan.video_prompts if kind == "video" else plan.prompts
            original = rev.prompt if kind == "video" else rev.parameters.get("image_prompt", "")
            prompt = overrides.get(UUID(scene.id), original)
            if not prompt.strip() or len(prompt) > 24000:
                raise FlowError(f"Falta un prompt válido de {kind} en «{scene.title}».")
            if kind == "video" and any(x in prompt for x in ("<video>", "<audio>", "<Audio ", "[Video", "<Video")) and UUID(scene.id) not in overrides:
                raise FlowError("Prepara un prompt de Flow en lenguaje natural; conserva el H3 original en Studio.")
            refs = []
            explicit = plan.references.get(UUID(scene.id))
            if kind == "image" and explicit is not None:
                if len(set(explicit)) != len(explicit):
                    raise FlowError("No repitas la misma imagen de referencia.")
                refs = [_reference(session, str(asset_id)) for asset_id in explicit]
            elif kind == "image":
                refs = [_reference(session, c["asset_id"]) for c in rev.parameters.get("cast", [])]
            elif plan.generation_mode != "image_video":
                if not rev.start_asset_id:
                    raise FlowError("Selecciona una imagen inicial aprobada antes de animar.")
                refs = [_reference(session, rev.start_asset_id)]
                if rev.end_asset_id:
                    refs.append(_reference(session, rev.end_asset_id))
            snapshot = {"title": scene.title, "scene_revision": scene.revision,
                        "revision_number": rev.number, "original_prompt": original, "prompt": prompt,
                        "image_prompt": rev.parameters.get("image_prompt", ""), "animation_prompt": rev.prompt,
                        "references": refs, "cast": copy.deepcopy(rev.parameters.get("cast", [])),
                        "aspect_ratio": plan.aspect_ratio or project.aspect_ratio,
                        "flow_tool": plan.flow_tool,
                        "flow_project_key": project_key or chapter.id,
                        "duration_seconds": (plan.duration_seconds or rev.duration_seconds) if kind == "video" else None,
                        "automatic_approval": plan.automatic_approval, "mode": connection.mode,
                        "agent_id": connection.agent_id, "use_provider_audio_in_montage": False}
            if connection.mode == "browser":
                from frutinovelas.services.flow_browser import IMAGE_RATIOS, VIDEO_RATIOS, VIDEO_SECONDS
                if kind == "video" and snapshot["duration_seconds"] not in VIDEO_SECONDS:
                    raise FlowError(f"Flow ofrece clips de {', '.join(map(str, VIDEO_SECONDS))} s; "
                                    f"«{scene.title}» pide {snapshot['duration_seconds']} s. No se redondea.")
                if snapshot["aspect_ratio"] not in (VIDEO_RATIOS if kind == "video" else IMAGE_RATIOS):
                    raise FlowError("Flow no ofrece esa relación de aspecto para este tipo de resultado.")
                if len(refs) > 3:
                    raise FlowError("El ejecutor de navegador admite hasta tres referencias por toma.")
            output.append(FlowJob(id=str(uuid5(plan.request_id, scene.id + ":" + kind)), batch_id=request_id,
                                 project_id=project.id, chapter_id=chapter.id, scene_id=scene.id,
                                 active_key=scene.id + ":" + kind, position=len(output), kind=kind,
                                 state="awaiting_approval" if kind == "video" and plan.generation_mode == "image_video" else "queued",
                                 dependency_id=image_id if kind == "video" and plan.generation_mode == "image_video" else None,
                                 snapshot=snapshot))
    session.add(FlowBatch(id=request_id, fingerprint=fid, project_id=project.id,
                          chapter_id=chapter.id, specification=spec))
    session.flush()
    session.add_all(output)
    scenes.audit(session, "flow.queued", "flow_batch", request_id, count=len(output))
    if commit:
        session.commit()
    else:
        session.flush()
    return output


def review(session, job, expected_revision, decision):
    if job.kind != "image" or job.state != "completed":
        raise FlowError("Solo se pueden revisar imágenes completadas.")
    if job.approval == decision:
        return job
    if job.approval != "pending":
        raise FlowError("Esta versión ya fue revisada. Conserva su historial y solicita otra versión si hace falta.")
    verified_path(job)
    scene = scenes.load_scene(session, job.scene_id)
    if scene.revision != expected_revision:
        raise scenes.Conflict(scene.revision)
    if decision == "approved":
        scenes.update_scene(session, scene, SceneUpdate(expected_revision=expected_revision, start_asset_id=job.result_asset_id))
    job.approval = decision
    children = session.scalars(select(FlowJob).where(FlowJob.dependency_id == job.id, FlowJob.state == "awaiting_approval"))
    for child in children:
        if decision == "rejected":
            change(session, child, "cancelled", "Imagen rechazada; no se animó.", remote_stopped=True)
        else:
            # The animation prompt stays frozen; a stale image cannot silently animate an edited scene.
            if expected_revision != job.snapshot["scene_revision"]:
                change(session, child, "failed", "La escena cambió. Solicita video con su nueva revisión.", remote_stopped=True)
            else:
                child.snapshot = {**child.snapshot, "references": [_reference(session, job.result_asset_id)],
                                  "approved_image_job_id": job.id, "approved_scene_revision": scene.revision}
                change(session, child, "queued")
    scenes.audit(session, "flow.review", "flow_job", job.id, decision=decision, scene_revision=scene.revision)
    session.commit()
    return job


def import_result(session, job, path):
    if job.state == "cancelled":
        raise FlowError("El trabajo se canceló. No se sobrescribirá su historial.")
    if job.state == "failed":
        raise FlowError("Crea un reintento antes de importar un resultado nuevo.")
    if job.state == "completed":
        if digest_file(path) != job.result_sha256:
            raise FlowError("Ya existe otro resultado para esta solicitud.")
        verified_path(job)
        return job
    if job.state == "awaiting_approval":
        raise FlowError("Primero aprueba la imagen de este video.")
    store_result(session, job, path)
    change(session, job, "completed", remote_stopped=True)
    scenes.audit(session, "flow.imported", "flow_job", job.id, sha256=job.result_sha256)
    session.commit()
    return job


def cancel(session, job):
    if job.state in TERMINAL:
        return job
    job.cancel_requested = True
    if job.state in ("queued", "awaiting_approval", "awaiting_import"):
        change(session, job, "cancelled", "Cancelación local. No detiene una generación iniciada manualmente en Flow.",
               remote_stopped=job.state != "awaiting_import")
    else:
        change(session, job, "cancel_requested", "El proveedor no confirmó la detención. La reserva se conserva.")
    # Also cancel the dependent video, without touching other scenes in the chapter.
    for child in session.scalars(select(FlowJob).where(FlowJob.dependency_id == job.id, FlowJob.state == "awaiting_approval")):
        change(session, child, "cancelled", "Se canceló la imagen inicial.", remote_stopped=True)
    session.commit()
    return job


BROWSER_RESOLVE_GRACE_SECONDS = 20 * 60


def resolve(session, job, confirmed, note):
    if not confirmed or job.state not in (*REMOTE, "awaiting_import", "cancelled"):
        raise FlowError("Comprueba en Flow que el trabajo ya no está activo antes de liberar la reserva.")
    if job.snapshot.get("mode") == "browser" and job.state in ("running", "downloading", "cancel_requested"):
        # A confirmed click can take minutes to show a tile. Releasing it early caused a
        # second real submission, so the bot must reconcile first or the grace must pass.
        changed = job.updated_at.replace(tzinfo=None) if job.updated_at else None
        elapsed = (utcnow().replace(tzinfo=None) - changed).total_seconds() if changed else 0
        if elapsed < BROWSER_RESOLVE_GRACE_SECONDS:
            minutes = int((BROWSER_RESOLVE_GRACE_SECONDS - elapsed) // 60) + 1
            raise FlowError("El bot confirmó este envío y Flow puede tardar en mostrar el resultado. "
                            f"Deja que el bot lo concilie o espera {minutes} min antes de liberarlo.")
    change(session, job, "cancelled", "Cierre verificado manualmente por el usuario.", remote_stopped=True, cancel_requested=True)
    scenes.audit(session, "flow.resolved", "flow_job", job.id, note=note)
    for child in session.scalars(select(FlowJob).where(FlowJob.dependency_id == job.id, FlowJob.state == "awaiting_approval")):
        change(session, child, "cancelled", "Se cerró la solicitud de imagen.", remote_stopped=True)
    session.commit()
    return job


def retry(session, job, request_id):
    existing = session.get(FlowJob, request_id)
    if existing:
        if existing.snapshot.get("retry_of") != job.id:
            raise FlowError("request_id pertenece a otra operación.")
        return existing
    if job.state not in ("failed", "cancelled") or not job.remote_stopped:
        raise FlowError("No se reenvían solicitudes inciertas. Reconcilia o importa su resultado.")
    if session.scalar(select(FlowJob.id).where(FlowJob.active_key == job.scene_id + ":" + job.kind)):
        raise FlowError("Ya existe otra solicitud activa para esta escena.")
    if job.kind == "video" and not job.snapshot["references"]:
        raise FlowError("Solicita una nueva secuencia imagen/video para conservar su relación.")
    replacement = FlowJob(id=request_id, batch_id=job.batch_id, project_id=job.project_id,
                          chapter_id=job.chapter_id, scene_id=job.scene_id,
                          active_key=job.scene_id + ":" + job.kind, position=job.position, kind=job.kind,
                          state="queued", snapshot={**copy.deepcopy(job.snapshot), "retry_of": job.id})
    session.add(replacement)
    # A failed image's pending animation must follow the new image, while both old
    # attempts stay in history. Never revive a video that the user already cancelled.
    children = list(session.scalars(select(FlowJob).where(
        FlowJob.dependency_id == job.id, FlowJob.state == "awaiting_approval")))
    for child in children:
        change(session, child, "cancelled", "La imagen se reintentó; se creó otra animación pendiente de aprobación.",
               remote_stopped=True)
    session.flush()  # Release the old unique scene/type reservation first.
    for child in children:
        session.add(FlowJob(id=str(uuid5(UUID(request_id), child.id + ":video")), batch_id=child.batch_id,
                            project_id=child.project_id, chapter_id=child.chapter_id, scene_id=child.scene_id,
                            active_key=child.scene_id + ":video", position=child.position, kind="video",
                            state="awaiting_approval", dependency_id=replacement.id,
                            snapshot={**copy.deepcopy(child.snapshot), "retry_of": child.id}))
    scenes.audit(session, "flow.retried", "flow_job", replacement.id, original=job.id)
    session.commit()
    return replacement


def agent_payload(session, job):
    references = []
    for ref in job.snapshot["references"]:
        frozen = _reference(session, ref["asset_id"])
        if frozen != ref:
            raise FlowError("La referencia cambió después de encolar.")
        asset = session.get(Asset, ref["asset_id"])
        raw = asset_path(get_settings(), asset).read_bytes()
        if len(raw) > 10 * 1024**2:
            raise FlowError("Una referencia supera 10 MiB; prepara una copia menor.")
        references.append({"content_base64": base64.b64encode(raw).decode(), "sha256": ref["sha256"]})
    return {"request_id": job.id, "kind": job.kind, "prompt": job.snapshot["prompt"],
            "aspect_ratio": job.snapshot["aspect_ratio"], "duration_seconds": job.snapshot["duration_seconds"],
            "flow_tool": job.snapshot.get("flow_tool", "standard"),
            "flow_project_key": job.snapshot.get("flow_project_key", job.chapter_id),
            "references": references, "expected_agent_id": job.snapshot["agent_id"]}
