"""Studio side of the Chromium/My Content executor.

The bot claims one job at a time through authenticated loopback endpoints. Studio
records the intent (``submitting``) before the bot touches Flow, so a crash can only
leave an uncertain reservation, never a silent second submission.

Flow project per story: ``flow_project_key`` (narrated video ID, or chapter ID for
chapter plans) maps to one Flow project URL. A key that is already mapped reuses that
project; a new key asks the bot to create a new project and report its URL *before*
submitting anything.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

from sqlalchemy import select

from frutinovelas.models import FlowConnection, FlowJob
from frutinovelas.services import flow, scenes
from frutinovelas.services.flow_transport import FlowError, flow_dir

# Models observed in the user's Flow UI. The bot verifies them and never substitutes.
IMAGE_MODEL = "Nano Banana 2.1"
VIDEO_MODEL = "Omni 1.1 Flash"
VIDEO_SECONDS = (4, 6, 8, 10)
IMAGE_RATIOS = ("16:9", "4:3", "1:1", "3:4", "9:16")
VIDEO_RATIOS = ("16:9", "9:16")
UNCERTAIN = ("submitting", "unknown")
CONFIRMED = ("running", "downloading")


def _projects_path():
    return flow_dir() / "browser_projects.json"


def project_map():
    path = _projects_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def valid_project_url(url):
    parts = urlsplit(url or "")
    return (parts.scheme == "https" and parts.hostname == "flow.google.com"
            and parts.path.startswith("/project/") and len(parts.path) > len("/project/")
            and not parts.username and not parts.password)


def record_project(session, job, url):
    """Bind a story key to its Flow project. An existing binding is never replaced."""
    if not valid_project_url(url):
        raise FlowError("La URL del proyecto Flow no es válida.")
    key = job.snapshot.get("flow_project_key") or job.chapter_id
    data = project_map()
    if key in data and data[key] != url:
        raise FlowError("Esta historia ya tiene otro proyecto Flow. No se reemplaza automáticamente.")
    data[key] = url
    path = _projects_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    scenes.audit(session, "flow.browser_project", "flow_job", job.id, key=key)
    session.commit()
    return key


def _browser_jobs(session, states):
    return list(session.scalars(select(FlowJob).where(FlowJob.state.in_(states))
                                .order_by(FlowJob.created_at, FlowJob.position)))


def _payload(session, job, action):
    if job.kind == "video":
        seconds = job.snapshot.get("duration_seconds")
        if seconds not in VIDEO_SECONDS:
            raise FlowError(f"Flow ofrece clips de {', '.join(map(str, VIDEO_SECONDS))} s; "
                            f"la toma pide {seconds} s. Ajusta la duración; no se redondea.")
        if job.snapshot["aspect_ratio"] not in VIDEO_RATIOS:
            raise FlowError("El video de Flow solo admite 16:9 o 9:16.")
    elif job.snapshot["aspect_ratio"] not in IMAGE_RATIOS:
        raise FlowError("Relación de aspecto no disponible en Flow.")
    payload = flow.agent_payload(session, job) if action == "submit" else {
        "request_id": job.id, "kind": job.kind, "flow_tool": job.snapshot.get("flow_tool", "standard"),
        "flow_project_key": job.snapshot.get("flow_project_key", job.chapter_id), "references": []}
    key = payload["flow_project_key"]
    payload.pop("expected_agent_id", None)
    payload.update(action=action, state=job.state, outputs=1,
                   model=VIDEO_MODEL if job.kind == "video" else IMAGE_MODEL,
                   flow_project_url=project_map().get(key))
    return payload


def claim(session):
    """Return the next action for the bot, registering intent before any submission."""
    connection = session.get(FlowConnection, "default")
    if not connection or not connection.connected or connection.mode != "browser":
        return {"action": "idle", "detail": "Flow no está conectado en modo navegador."}
    pending = [j for j in _browser_jobs(session, (*flow.REMOTE, "awaiting_import"))
               if j.snapshot.get("mode") == "browser"]
    if pending:
        job = pending[0]
        if job.state in CONFIRMED:
            return _payload(session, job, "recover")
        if job.state in UNCERTAIN:
            return _payload(session, job, "reconcile")
        return {"action": "blocked", "request_id": job.id, "state": job.state,
                "detail": job.error or "Hay un trabajo que requiere revisión en Studio."}
    queued = [j for j in _browser_jobs(session, ("queued",)) if j.snapshot.get("mode") == "browser"]
    if not queued:
        return {"action": "idle", "detail": "No hay trabajos Flow pendientes."}
    job = sorted(queued, key=lambda j: (j.kind, j.created_at, j.position))[0]
    try:
        payload = _payload(session, job, "submit")
    except FlowError as exc:
        flow.change(session, job, "failed", str(exc), remote_stopped=True)
        session.commit()
        return {"action": "idle", "detail": str(exc)}
    flow.change(session, job, "submitting")
    session.commit()
    payload["state"] = job.state
    return payload


def report(session, job, event, *, error="", project_url=None):
    """Apply one bot event. Only an explicit pre-click stop releases the reservation."""
    if job.snapshot.get("mode") != "browser":
        raise FlowError("Este trabajo no pertenece al ejecutor de navegador.")
    if event == "project":
        record_project(session, job, project_url)
        return job
    if job.state in flow.TERMINAL:
        return job
    if event == "submitted":
        if job.state not in UNCERTAIN:
            raise FlowError("El trabajo no estaba en envío.")
        flow.change(session, job, "cancel_requested" if job.cancel_requested else "running",
                    "Cancelación local solicitada; Flow no se detiene desde Studio." if job.cancel_requested else "")
    elif event == "not_submitted":
        # The bot proved it stopped before pressing Start generation.
        if job.state not in UNCERTAIN:
            raise FlowError("Ya hay una generación confirmada; no se marca como no enviada.")
        flow.change(session, job, "failed", error or "El bot se detuvo antes de enviar.", remote_stopped=True)
        for child in session.scalars(select(FlowJob).where(FlowJob.dependency_id == job.id,
                                                           FlowJob.state == "awaiting_approval")):
            flow.change(session, child, "cancelled", "La imagen inicial no se generó.", remote_stopped=True)
    elif event == "downloading":
        if job.state not in (*CONFIRMED, "cancel_requested"):
            raise FlowError("Solo se descarga una generación confirmada.")
        flow.change(session, job, "downloading")
    elif event == "uncertain":
        flow.change(session, job, "unknown", error or "Estado incierto en Flow. Se conserva la reserva.")
    elif event == "blocked":
        flow.change(session, job, "blocked", error or "Flow pidió intervención humana.")
    else:
        raise FlowError("Evento del bot no admitido.")
    session.commit()
    return job


def import_browser_result(session, job, path):
    if job.snapshot.get("mode") != "browser":
        raise FlowError("Este trabajo no pertenece al ejecutor de navegador.")
    if job.state in UNCERTAIN:
        raise FlowError("Confirma el envío antes de importar el resultado.")
    return flow.import_result(session, job, path)
