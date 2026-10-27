"""Audio-first narration editor. Transcripts are user supplied; speech recognition is not claimed."""
from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from frutinovelas.config import get_settings
from frutinovelas.db import get_session
from frutinovelas.models import Asset, Chapter, ComfyConnection, FlowJob, NarratedVideo, Project, Scene
from frutinovelas.schemas.narrated import (
    NarratedCreate, NarratedFlowRequest, NarratedPlanRequest, NarratedRenderRequest, NarratedSelectVersion,
    NarratedShot, NarratedSyncRequest, NarratedUpdate,
)
from frutinovelas.services import flow, scenes
from frutinovelas.services.assets import asset_path, AssetError
from frutinovelas.services.flow_transport import FlowError
from frutinovelas.services.narrated_remote import start_remote_video

router = APIRouter(tags=["videos narrados"])


def _get(session, id):
    row = session.get(NarratedVideo, id)
    if row is None:
        raise HTTPException(404, "Video narrado no encontrado.")
    return row


def _flow_chapter(session, row):
    for shot in row.shots:
        if shot.get("flow_scene_id"):
            scene = session.get(Scene, shot["flow_scene_id"])
            if scene:
                return scene.chapter_id
    return None


def _out(session, row):
    duration = session.get(Asset, row.audio_asset_id).duration_seconds
    return dict(id=row.id, project_id=row.project_id, title=row.title,
                audio_asset_id=row.audio_asset_id, audio_duration=duration,
                transcript=row.transcript, aspect_ratio=row.aspect_ratio, shots=row.shots,
                revision=row.revision, state=row.state, progress=row.progress,
                flow_chapter_id=_flow_chapter(session, row),
                error=row.error, result_url=f"/api/v1/narrated-videos/{row.id}/content" if row.state=="completed" else None)


def _audio(session, asset_id):
    asset = session.get(Asset, asset_id)
    if not asset or asset.kind != "narration" or not asset.duration_seconds:
        raise HTTPException(422, "Selecciona una narración válida de hasta cinco minutos.")
    if not 0 < asset.duration_seconds <= 300:
        raise HTTPException(422, "La narración debe durar como máximo cinco minutos.")
    return asset


def _links(session, project_id, idx, s):
    """Flow links are server managed: a shot may only point at its own project's queue."""
    if s.flow_scene_id:
        scene = session.get(Scene, s.flow_scene_id)
        chapter = session.get(Chapter, scene.chapter_id) if scene else None
        if not chapter or chapter.project_id != project_id:
            raise HTTPException(422, f"La toma {idx+1} apunta a una escena Flow de otro proyecto.")
    for field, kind in (("flow_image_job_id", "image"), ("flow_video_job_id", "video"), ("selected_image_job_id", "image")):
        identifier = getattr(s, field)
        if not identifier:
            continue
        job = session.get(FlowJob, identifier)
        if (not job or job.project_id != project_id or job.kind != kind
                or not s.flow_scene_id or job.scene_id != s.flow_scene_id):
            raise HTTPException(422, f"La toma {idx+1} apunta a un resultado Flow ajeno.")
    for ref in s.references:
        asset = session.get(Asset, str(ref.asset_id))
        if not asset or asset.kind != "image":
            raise HTTPException(422, f"La referencia de la toma {idx+1} no es una imagen registrada.")


def _shots(session, shots, duration, require_images=False, project_id=None):
    if not shots:
        raise HTTPException(422, "El video necesita al menos una toma.")
    if len(shots)>90:
        raise HTTPException(422, "Se admiten hasta 90 tomas.")
    last=0.0
    for idx, shot in enumerate(shots):
        s = NarratedShot.model_validate(shot)
        if abs(s.start_seconds-last)>0.06:
            raise HTTPException(422, f"La toma {idx+1} debe comenzar donde termina la anterior.")
        if s.end_seconds > duration + .05:
            raise HTTPException(422, "Las tomas no pueden superar la duración del audio.")
        if project_id is not None:
            _links(session, project_id, idx, s)
        if require_images:
            asset=session.get(Asset,s.image_asset_id) if s.image_asset_id else None
            if not asset or asset.kind!="image":
                raise HTTPException(422, f"Asigna una imagen a la toma {idx+1}.")
            try:
                path=asset_path(get_settings(),asset)
            except AssetError:
                raise HTTPException(422,"Ruta de imagen inválida.")
            if not path.is_file():
                raise HTTPException(422, f"Falta la imagen de la toma {idx+1}.")
        last=s.end_seconds
    if abs(last-duration)>.06:
        raise HTTPException(422,"Las tomas deben cubrir toda la narración, sin huecos.")


@router.post("/assets/narration", status_code=201)
def upload_narration(file: UploadFile=File(...), session: Session=Depends(get_session)):
    settings=get_settings()
    probe=shutil.which(settings.ffprobe_path)
    if not probe:
        raise HTTPException(422,"Instala FFprobe (incluido con FFmpeg) para validar audios largos.")
    tmp=settings.tmp_dir / f"narration-{uuid.uuid4().hex}"
    digest=hashlib.sha256()
    size=0
    try:
        with tmp.open("wb") as f:
            while chunk:=file.file.read(1024*1024):
                size+=len(chunk)
                if size>settings.max_upload_mb*1024*1024:
                    raise HTTPException(413,f"Supera el límite de {settings.max_upload_mb} MB.")
                digest.update(chunk)
                f.write(chunk)
        if not size:
            raise HTTPException(422,"El audio está vacío.")
        result=subprocess.run([probe,"-v","error","-show_entries",
                               "format=duration,format_name:stream=codec_type,channels",
                               "-of","json",str(tmp)],capture_output=True,text=True,timeout=25)
        if result.returncode:
            raise HTTPException(422,"No se pudo validar el archivo de audio.")
        import json
        info=json.loads(result.stdout)
        streams=info.get("streams",[])
        audios=[s for s in streams if s.get("codec_type")=="audio"]
        if len(audios)!=1 or any(s.get("codec_type")=="video" for s in streams):
            raise HTTPException(422,"Sube solo una pista de audio, sin video.")
        duration=float(info["format"]["duration"])
        if not math.isfinite(duration) or duration<=0 or duration>300:
            raise HTTPException(422,"La narración debe durar entre 0 y 300 segundos.")
        formats=set(info["format"].get("format_name","").split(","))
        options=[("wav","audio/wav",".wav"),("mp3","audio/mpeg",".mp3"),
                 ("mov","audio/mp4",".m4a"),("aac","audio/aac",".aac"),
                 ("flac","audio/flac",".flac"),("ogg","audio/ogg",".ogg"),
                 ("matroska","audio/webm",".webm")]
        kind=next(((mime,ext) for fmt,mime,ext in options if fmt in formats),None)
        if kind is None:
            raise HTTPException(422,"Formato no admitido. Usa WAV, MP3, M4A, AAC, FLAC, OGG o WebM.")
        sha=digest.hexdigest()
        old=session.scalar(select(Asset).where(Asset.sha256==sha))
        if old:
            if old.kind!="narration":
                raise HTTPException(422,"El archivo ya existe como recurso de otro tipo.")
            return _asset_out(old)
        relative=Path("assets")/sha[:2]/(sha+kind[1])
        dest=settings.resolved_data_dir/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        os.replace(tmp,dest)
        asset=Asset(kind="narration",rel_path=relative.as_posix(),sha256=sha,size_bytes=size,
                    mime=kind[0],duration_seconds=duration,width=None,height=None,
                    original_name=Path(file.filename or "narracion").name[:300])
        session.add(asset)
        session.commit()
        return _asset_out(asset)
    except (subprocess.TimeoutExpired, ValueError, KeyError, OSError) as exc:
        raise HTTPException(422,"No se pudo procesar la narración.") from exc
    finally:
        tmp.unlink(missing_ok=True)


def _asset_out(a):
    return dict(id=a.id,kind=a.kind,mime=a.mime,duration_seconds=a.duration_seconds,
                original_name=a.original_name,sha256=a.sha256,size_bytes=a.size_bytes)


@router.post("/projects/{project_id}/narrated-videos",status_code=201)
def create(project_id:str, body:NarratedCreate, session:Session=Depends(get_session)):
    if session.get(Project,project_id) is None:
        raise HTTPException(404,"Proyecto no encontrado.")
    audio=_audio(session,body.audio_asset_id)
    shots=[s.model_dump(mode="json") for s in body.shots] if body.shots is not None else [NarratedShot(start_seconds=0,end_seconds=audio.duration_seconds).model_dump(mode="json")]
    _shots(session,shots,audio.duration_seconds,project_id=project_id)
    row=NarratedVideo(project_id=project_id,title=body.title,audio_asset_id=audio.id,transcript=body.transcript,
                      aspect_ratio=body.aspect_ratio,shots=shots)
    session.add(row);session.commit()
    return _out(session,row)


@router.get("/projects/{project_id}/narrated-videos")
def listing(project_id:str,session:Session=Depends(get_session)):
    return [_out(session,r) for r in session.scalars(select(NarratedVideo).where(NarratedVideo.project_id==project_id).order_by(NarratedVideo.created_at.desc()))]


@router.get("/narrated-videos/{id}")
def get(id:str,session:Session=Depends(get_session)):
    return _out(session,_get(session,id))


@router.patch("/narrated-videos/{id}")
def update(id:str,body:NarratedUpdate,session:Session=Depends(get_session)):
    row=_get(session,id)
    if row.revision!=body.expected_revision:
        raise HTTPException(409,"El proyecto cambió. Recarga antes de guardar.")
    if row.state in ("queued","rendering"):
        raise HTTPException(409,"No edites mientras se exporta.")
    payload=body.model_dump(mode="json",exclude_unset=True,exclude={"expected_revision"})
    duration=_audio(session,payload.get("audio_asset_id",row.audio_asset_id)).duration_seconds
    shots=payload["shots"] if "shots" in payload else row.shots
    _shots(session,shots,duration,project_id=row.project_id)
    for field,value in payload.items():
        setattr(row,field,value)
    row.revision+=1
    row.state="draft";row.progress=0;row.result_path=None;row.error=""
    session.commit()
    return _out(session,row)


def _clip_shots(session, row):
    """Animated shots must have a verified Flow clip; never fall back silently to a still."""
    from frutinovelas.services.narrated_automation import completed_clip
    used = False
    for idx, shot in enumerate(row.shots):
        if shot.get("media_mode") != "animated":
            continue
        try:
            completed_clip(session, row, shot)
        except FlowError as exc:
            raise HTTPException(422, f"Toma {idx+1}: {exc}") from exc
        used = True
    return used


@router.post("/narrated-videos/{id}/render",status_code=202)
def render(id:str,body:NarratedRenderRequest,session:Session=Depends(get_session)):
    row=_get(session,id)
    if row.revision!=body.expected_revision:
        raise HTTPException(409,"El proyecto cambió. Recarga antes de generar.")
    if row.state in ("queued","rendering"):
        raise HTTPException(409,"Hay un montaje en curso.")
    _shots(session,row.shots,_audio(session,row.audio_asset_id).duration_seconds,require_images=True)
    clips=_clip_shots(session,row)
    remote=session.get(ComfyConnection,"default") is not None
    engine=body.engine if body.engine!="auto" else ("local" if clips or not remote else "remote")
    if engine=="remote" and clips:
        raise HTTPException(422,"El montaje remoto no recibe clips de Flow. Usa el montaje local con FFmpeg.")
    if engine=="remote" and not remote:
        raise HTTPException(409,"Conecta RunPod/Colab o usa el montaje local.")
    row.state="queued";row.error="";row.progress=0
    session.commit()
    if engine=="local":
        from frutinovelas.services.narrated import start_video
        start_video(row.id)
    else:
        start_remote_video(row.id)
    return {**_out(session,row),"engine":engine}


# --- Flow automation for narrated videos -------------------------------------------
# Same story (this narrated video) -> same Flow project key. A different video is a
# different story and gets its own Flow project in the browser executor.

def _flow_guard(request: Request, row):
    from frutinovelas.routes.flow import guard, scope
    guard(request)
    scope(request, row.project_id)


def _flow_error(session, exc):
    session.rollback()
    code = 404 if isinstance(exc, scenes.NotFound) else 409 if isinstance(exc, (FlowError, scenes.Conflict)) else 422
    return HTTPException(code, str(exc))


def _with_jobs(session, row, jobs):
    session.refresh(row)
    return {"video": _out(session, row), "jobs": [flow.public_job(j) for j in jobs]}


@router.post("/narrated-videos/{id}/plan")
def plan(id: str, body: NarratedPlanRequest, request: Request, session: Session = Depends(get_session)):
    """Qwen prepares shots over the full narration; the transcript and audio stay untouched."""
    from frutinovelas.services import narrated_automation as automation
    row = _get(session, id)
    _flow_guard(request, row)
    if row.revision != body.expected_revision or row.state in ("queued", "rendering"):
        raise HTTPException(409, "El proyecto cambió o está exportándose. Recarga antes de planificar.")
    if any(shot.get("flow_scene_id") for shot in row.shots):
        raise HTTPException(409, "Las tomas ya están vinculadas a Flow; no se reemplazan automáticamente.")
    try:
        shots = automation.plan_storyboard(session, row, body)
    except (FlowError, OSError) as exc:
        raise _flow_error(session, exc if isinstance(exc, FlowError) else FlowError("No se pudo consultar Qwen.")) from exc
    _shots(session, shots, _audio(session, row.audio_asset_id).duration_seconds, project_id=row.project_id)
    row.shots = shots
    row.state, row.progress, row.result_path, row.error = "draft", 0, None, ""
    row.revision += 1
    session.commit()
    return _out(session, row)


@router.post("/narrated-videos/{id}/flow", status_code=202)
def dispatch(id: str, body: NarratedFlowRequest, request: Request, session: Session = Depends(get_session)):
    from frutinovelas.services import narrated_automation as automation
    row = _get(session, id)
    _flow_guard(request, row)
    try:
        with flow.operation_lock():
            jobs = automation.dispatch_flow(session, row, body)
    except (FlowError, scenes.Conflict, scenes.NotFound) as exc:
        raise _flow_error(session, exc) from exc
    return _with_jobs(session, row, jobs)


@router.post("/narrated-videos/{id}/animate", status_code=202)
@router.post("/narrated-videos/{id}/flow/animate", status_code=202, include_in_schema=False)
def animate(id: str, body: NarratedFlowRequest, request: Request, session: Session = Depends(get_session)):
    from frutinovelas.services import narrated_automation as automation
    row = _get(session, id)
    _flow_guard(request, row)
    try:
        with flow.operation_lock():
            jobs = automation.animate_existing_images(session, row, body)
    except (FlowError, scenes.Conflict, scenes.NotFound, scenes.Invalid) as exc:
        raise _flow_error(session, exc) from exc
    return _with_jobs(session, row, jobs)


@router.post("/narrated-videos/{id}/sync")
@router.post("/narrated-videos/{id}/flow/sync", include_in_schema=False)
def sync(id: str, body: NarratedSyncRequest, request: Request, session: Session = Depends(get_session)):
    from frutinovelas.services import narrated_automation as automation
    row = _get(session, id)
    _flow_guard(request, row)
    if row.revision != body.expected_revision:
        raise HTTPException(409, "El proyecto cambió. Recarga antes de sincronizar.")
    if row.state in ("queued", "rendering"):
        raise HTTPException(409, "No sincronices mientras se monta el video.")
    try:
        statuses = automation.sync_results(session, row)
    except FlowError as exc:
        raise _flow_error(session, exc) from exc
    ids = [s["id"] for s in statuses]
    jobs = [session.get(FlowJob, i) for i in ids]
    return _with_jobs(session, row, [j for j in jobs if j])


@router.get("/narrated-videos/{id}/shots/{index}/versions")
def shot_versions(id: str, index: int, request: Request, session: Session = Depends(get_session)):
    from frutinovelas.services import narrated_automation as automation
    row = _get(session, id)
    _flow_guard(request, row)
    try:
        return [flow.public_job(j) for j in automation.versions(session, row, index)]
    except FlowError as exc:
        raise _flow_error(session, exc) from exc


@router.post("/narrated-videos/{id}/select-version")
def select_version(id: str, body: NarratedSelectVersion, request: Request, session: Session = Depends(get_session)):
    from frutinovelas.services import narrated_automation as automation
    row = _get(session, id)
    _flow_guard(request, row)
    try:
        job = automation.select_version(session, row, body)
    except FlowError as exc:
        raise _flow_error(session, exc) from exc
    return _with_jobs(session, row, [job])


@router.get("/narrated-videos/{id}/content")
def content(id:str,session:Session=Depends(get_session)):
    row=_get(session,id)
    if row.state!="completed" or not row.result_path:
        raise HTTPException(404,"El video aún no está disponible.")
    base=get_settings().resolved_data_dir
    path=(base/row.result_path).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(404,"Archivo de video no disponible.")
    return FileResponse(path,media_type="video/mp4",filename=path.name)


@router.delete("/narrated-videos/{id}/output")
def delete_output(id: str, session: Session = Depends(get_session)):
    """Delete only the completed local and remote export, preserving audio and shots."""
    row = _get(session, id)
    if row.state in ("queued", "rendering"):
        raise HTTPException(409, "No puedes eliminar un video mientras se exporta.")
    from frutinovelas.services.comfy import ComfyClient, ComfyError
    from frutinovelas.services.generation import connection_token

    connection = session.get(ComfyConnection, "default")
    if connection:
        client = ComfyClient(connection.url, connection_token(connection))
        try:
            client.request("DELETE", f"/frutinovelas/narration/jobs/{row.id}")
        except (ComfyError, OSError) as exc:
            raise HTTPException(503, "No se pudo comprobar la eliminación remota. Reintenta con RunPod/Colab conectado.") from exc
        finally:
            client.close()
    if row.result_path:
        base = get_settings().resolved_data_dir
        path = (base / row.result_path).resolve()
        if base not in path.parents:
            raise HTTPException(422, "Ruta no válida.")
        path.unlink(missing_ok=True)
    row.result_path = None
    row.state = "draft"
    row.error = ""
    row.progress = 0
    session.commit()
    return _out(session, row)
