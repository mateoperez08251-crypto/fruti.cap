"""Narrow Flow endpoints: registered scene IDs and media, never arbitrary desktop actions."""
import secrets
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from frutinovelas.config import get_settings
from frutinovelas.db import get_session
from frutinovelas.models import Asset, FlowConnection, FlowJob
from frutinovelas.schemas.flow import FlowConnect, FlowImport, FlowPlan, FlowResolve, FlowRetry, FlowReview
from frutinovelas.services import flow, scenes
from frutinovelas.services.assets import asset_path
from frutinovelas.services.flow_media import verified_path
from frutinovelas.services.flow_transport import FlowClient, FlowError, flow_dir, local_secret


def guard(request: Request):
    settings = get_settings()
    key = request.headers.get("x-fruti-flow-key", "")
    request.state.flow_mcp = bool(key and secrets.compare_digest(key, local_secret("mcp")))
    if key and not request.state.flow_mcp:
        raise HTTPException(401, "Credencial Flow inválida.")
    if request.state.flow_mcp:
        if request.method not in ("GET", "HEAD") and settings.mcp_access_mode != "read_write":
            raise HTTPException(403, "MCP está en modo de solo lectura.")
        return
    host = request.client.host if request.client else ""
    origin = request.headers.get("origin")
    expected = {str(request.base_url).rstrip("/"), *settings.cors_origins}
    if (host not in ("127.0.0.1", "::1", "testclient")
            or urlsplit(str(request.url)).hostname not in ("localhost", "127.0.0.1", "::1", "testserver")
            or "forwarded" in request.headers or "x-forwarded-for" in request.headers
            or (origin and origin not in expected)
            or request.headers.get("sec-fetch-site") == "cross-site"):
        raise HTTPException(403, "Flow solo admite la interfaz local o MCP autenticado.")


def scope(request, project_id):
    allowed = get_settings().mcp_project_id
    if request.state.flow_mcp and allowed and str(project_id) != allowed:
        raise HTTPException(403, "Este proyecto está fuera del permiso MCP.")


def error(exc):
    return HTTPException(404 if isinstance(exc, scenes.NotFound) else 409 if isinstance(exc, (scenes.Conflict, FlowError)) else 422, str(exc))


router = APIRouter(prefix="/flow", tags=["Flow Automation"], dependencies=[Depends(guard)])


def agent_status():
    client = None
    try:
        client = FlowClient()
        result = client.request("GET", "status")
        required = {"available", "window_open", "flow_available", "authentication", "modes", "detail"}
        if not isinstance(result, dict) or not required.issubset(result):
            raise FlowError("Respuesta del agente incompleta.")
        return {**result, "reachable": True}
    except (httpx.HTTPError, FlowError, ValueError, OSError):
        return {"reachable": False, "profile_configured": None, "available": False,
                "window_open": None, "flow_available": None, "authentication": "unknown",
                "modes": {}, "detail": "No se pudo consultar el agente Windows. Inicia iniciar_flow_agente.cmd en este equipo. Si ya está abierto, revisa su terminal y que use el mismo directorio de datos que Studio."}
    finally:
        if client is not None:
            client.close()


@router.get("/status")
def status(session: Session = Depends(get_session)):
    connection = session.get(FlowConnection, "default")
    return {"connected": bool(connection and connection.connected), "mode": connection.mode if connection else "assisted",
            "agent": agent_status(), "providers": {"image": ["qwen", "flow"], "video": ["minimax_h3", "flow"]}}


@router.get("/detect")
def detect():
    return agent_status()


@router.post("/connect")
def connect(body: FlowConnect, session: Session = Depends(get_session)):
    if not body.authorized:
        raise HTTPException(422, "Confirma que tienes autorización para usar este controlador con tu sesión.")
    agent = agent_status() if body.mode == "uia" else {}
    if body.mode == "uia" and (not agent.get("available") or not agent.get("modes")):
        raise HTTPException(409, "Primero configura y verifica el perfil de controles en el agente Windows.")
    with flow.operation_lock():
        connection = session.get(FlowConnection, "default")
        if connection is None:
            connection = FlowConnection(id="default")
            session.add(connection)
        agent_id = agent.get("agent_id", "")
        if connection.agent_id != agent_id and session.scalar(select(FlowJob.id).where(FlowJob.state.in_(flow.REMOTE))):
            raise HTTPException(409, "Hay trabajo remoto incierto. Reconcilia antes de cambiar de agente.")
        connection.connected, connection.mode, connection.agent_id = True, body.mode, agent_id
        scenes.audit(session, "flow.connected", "flow_connection", "default", mode=body.mode)
        session.commit()
    return {"connected": True, "mode": body.mode}


@router.post("/disconnect")
def disconnect(session: Session = Depends(get_session)):
    with flow.operation_lock():
        connection = session.get(FlowConnection, "default")
        if connection:
            connection.connected = False
            session.commit()
    return {"connected": False, "remote_stopped": False, "detail": "Se pausó la cola local; los trabajos remotos se conservan."}


@router.post("/focus")
def focus():
    client = FlowClient()
    try:
        return client.request("POST", "focus", {})
    except (httpx.HTTPError, FlowError) as exc:
        raise HTTPException(409, "No se pudo enfocar la ventana autorizada.") from exc
    finally:
        client.close()


@router.post("/generate", status_code=202)
def generate(body: FlowPlan, request: Request, session: Session = Depends(get_session)):
    scope(request, body.project_id)
    try:
        with flow.operation_lock():
            return [flow.public_job(j) for j in flow.enqueue_plan(session, body)]
    except (FlowError, scenes.Conflict) as exc:
        raise error(exc) from exc


@router.get("/jobs")
def list_jobs(project_id: UUID, request: Request, chapter_id: UUID | None = None, session: Session = Depends(get_session)):
    scope(request, project_id)
    query = select(FlowJob).where(FlowJob.project_id == str(project_id))
    if chapter_id:
        query = query.where(FlowJob.chapter_id == str(chapter_id))
    return [flow.public_job(j) for j in session.scalars(query.order_by(FlowJob.created_at.desc(), FlowJob.position).limit(500))]


def scoped_job(session, request, job_id):
    try:
        job = flow.get_job(session, str(job_id))
        scope(request, job.project_id)
        return job
    except scenes.NotFound as exc:
        raise error(exc) from exc


@router.get("/jobs/{job_id}")
def job_detail(job_id: UUID, request: Request, session: Session = Depends(get_session)):
    return flow.public_job(scoped_job(session, request, job_id), details=True)


@router.get("/jobs/{job_id}/content")
def content(job_id: UUID, request: Request, session: Session = Depends(get_session)):
    job = scoped_job(session, request, job_id)
    try:
        return FileResponse(verified_path(job), media_type=job.result_mime,
                            filename=f"Flow-{job.id}" + (".mp4" if job.kind == "video" else "." + (job.result_mime or "image/png").split("/")[-1]))
    except FlowError as exc:
        raise HTTPException(409, str(exc)) from exc


def mutate(session, request, job_id, callback):
    try:
        with flow.operation_lock():
            return flow.public_job(callback(scoped_job(session, request, job_id)))
    except (FlowError, scenes.Conflict, scenes.Invalid, ValueError) as exc:
        raise error(exc) from exc


@router.post("/jobs/{job_id}/review")
def review(job_id: UUID, body: FlowReview, request: Request, session: Session = Depends(get_session)):
    return mutate(session, request, job_id, lambda j: flow.review(session, j, body.expected_revision, body.decision))


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: UUID, request: Request, session: Session = Depends(get_session)):
    return mutate(session, request, job_id, lambda j: flow.cancel(session, j))


@router.post("/jobs/{job_id}/resolve")
def resolve(job_id: UUID, body: FlowResolve, request: Request, session: Session = Depends(get_session)):
    # Reconciliation attestation must come from the local human, never a remote MCP client.
    if request.state.flow_mcp:
        raise HTTPException(403, "La reconciliación manual se realiza desde Studio en este equipo.")
    return mutate(session, request, job_id, lambda j: flow.resolve(session, j, body.confirmed_no_remote_work, body.note))


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry(job_id: UUID, body: FlowRetry, request: Request, session: Session = Depends(get_session)):
    return mutate(session, request, job_id, lambda j: flow.retry(session, j, str(body.request_id)))


@router.post("/jobs/{job_id}/import-asset")
def import_asset(job_id: UUID, body: FlowImport, request: Request, session: Session = Depends(get_session)):
    job = scoped_job(session, request, job_id)
    asset = session.get(Asset, str(body.asset_id))
    if job.kind != "image" or not asset or asset.kind != "image":
        raise HTTPException(422, "Indica una imagen ya registrada en Studio.")
    return mutate(session, request, job_id, lambda j: flow.import_result(session, j, asset_path(get_settings(), asset)))


@router.post("/jobs/{job_id}/import")
def import_file(job_id: UUID, request: Request, file: UploadFile, session: Session = Depends(get_session)):
    job = scoped_job(session, request, job_id)
    limit = (get_settings().flow_max_video_mb if job.kind == "video" else get_settings().max_upload_mb) * 1024**2
    import uuid
    path = flow_dir() / ("upload-" + uuid.uuid4().hex + ".part")
    try:
        count = 0
        with path.open("xb") as stream:
            while chunk := file.file.read(1024**2):
                count += len(chunk)
                if count > limit:
                    raise HTTPException(413, "El resultado supera el límite de tamaño.")
                stream.write(chunk)
        return mutate(session, request, job_id, lambda j: flow.import_result(session, j, path))
    finally:
        path.unlink(missing_ok=True)
        file.file.close()
