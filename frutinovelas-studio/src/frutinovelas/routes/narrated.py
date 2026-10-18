"""Audio-first narration editor. Transcripts are user supplied; speech recognition is not claimed."""
from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from frutinovelas.config import get_settings
from frutinovelas.db import get_session
from frutinovelas.models import Asset, NarratedVideo, Project
from frutinovelas.schemas.narrated import NarratedCreate, NarratedUpdate, NarratedRenderRequest, NarratedShot
from frutinovelas.services.assets import asset_path, AssetError
from frutinovelas.services.narrated import start_video

router = APIRouter(tags=["videos narrados"])


def _get(session, id):
    row = session.get(NarratedVideo, id)
    if row is None:
        raise HTTPException(404, "Video narrado no encontrado.")
    return row


def _out(session, row):
    duration = session.get(Asset, row.audio_asset_id).duration_seconds
    return dict(id=row.id, project_id=row.project_id, title=row.title,
                audio_asset_id=row.audio_asset_id, audio_duration=duration,
                transcript=row.transcript, aspect_ratio=row.aspect_ratio, shots=row.shots,
                revision=row.revision, state=row.state, progress=row.progress,
                error=row.error, result_url=f"/api/v1/narrated-videos/{row.id}/content" if row.state=="completed" else None)


def _audio(session, asset_id):
    asset = session.get(Asset, asset_id)
    if not asset or asset.kind != "narration" or not asset.duration_seconds:
        raise HTTPException(422, "Selecciona una narración válida de hasta cinco minutos.")
    if not 0 < asset.duration_seconds <= 300:
        raise HTTPException(422, "La narración debe durar como máximo cinco minutos.")
    return asset


def _shots(session, shots, duration, require_images=False):
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
    shots=[s.model_dump() for s in body.shots] if body.shots is not None else [NarratedShot(start_seconds=0,end_seconds=audio.duration_seconds).model_dump()]
    _shots(session,shots,audio.duration_seconds)
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
    payload=body.model_dump(exclude_unset=True,exclude={"expected_revision"})
    duration=_audio(session,payload.get("audio_asset_id",row.audio_asset_id)).duration_seconds
    shots=payload["shots"] if "shots" in payload else row.shots
    _shots(session,shots,duration)
    for field,value in payload.items():
        setattr(row,field,value)
    row.revision+=1
    row.state="draft";row.progress=0;row.result_path=None;row.error=""
    session.commit()
    return _out(session,row)


@router.post("/narrated-videos/{id}/render",status_code=202)
def render(id:str,body:NarratedRenderRequest,session:Session=Depends(get_session)):
    row=_get(session,id)
    if row.revision!=body.expected_revision:
        raise HTTPException(409,"El proyecto cambió. Recarga antes de generar.")
    if row.state in ("queued","rendering"):
        raise HTTPException(409,"Hay un montaje en curso.")
    _shots(session,row.shots,_audio(session,row.audio_asset_id).duration_seconds,require_images=True)
    row.state="queued";row.error="";row.progress=0
    session.commit()
    start_video(row.id)
    return _out(session,row)


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
