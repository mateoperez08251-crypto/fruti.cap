"""RunPod/Colab narration assembly coordinator.

The long-form audio and still images are uploaded via the existing authenticated
Comfy gateway. Only a completed MP4 is downloaded to Studio. No local FFmpeg
assembly takes place.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from threading import Thread
from time import sleep

import httpx
from sqlalchemy.orm import Session

from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.models import Asset, ComfyConnection, NarratedVideo
from frutinovelas.services.assets import asset_path
from frutinovelas.services.comfy import ComfyClient, ComfyError, identity_key
from frutinovelas.services.generation import connection_token

MIME = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
        ".flac": "audio/flac", ".aac": "audio/aac", ".ogg": "audio/ogg", ".webm": "audio/webm",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
API = "/frutinovelas/narration"


def _publish(client: ComfyClient, path: Path, kind: str, sha: str) -> str:
    with path.open("rb") as stream:
        response = client.request("POST", API + "/assets",
                                  data={"kind": kind},
                                  files={"file": (path.name, stream, MIME.get(path.suffix.lower(), "application/octet-stream"))})
    result = response.json()
    if result.get("id") != sha or result.get("kind") != kind:
        raise ComfyError("El servidor remoto devolvió una identidad de archivo incorrecta.")
    return sha


def _update(video_id: str, *, state=None, progress=None, error=None, result_path=None):
    with session_factory()() as session:
        row = session.get(NarratedVideo, video_id)
        if row is None:
            return
        if state is not None:
            row.state = state
        if progress is not None:
            row.progress = progress
        if error is not None:
            row.error = error
        if result_path is not None:
            row.result_path = result_path
        session.commit()


def _export(video_id: str):
    client = None
    try:
        with session_factory()() as session:
            row = session.get(NarratedVideo, video_id)
            if row is None or row.state != "queued":
                return
            connection = session.get(ComfyConnection, "default")
            if connection is None:
                raise ComfyError("Configura ComfyUI remoto en Studio para realizar la unión.")
            client = ComfyClient(connection.url, connection_token(connection))
            identity = client.get("/frutinovelas/identity")
            if identity_key(identity) != identity_key(connection.identity):
                raise ComfyError("RunPod/Colab cambió de sesión: usa Guardar y comprobar antes del montaje.")
            capabilities = client.get(API + "/capabilities")
            if not capabilities.get("supported") or not capabilities.get("ffmpeg"):
                raise ComfyError("Actualiza el kit remoto para disponer del montaje narrado FFmpeg.")
            audio = session.get(Asset, row.audio_asset_id)
            if not audio or audio.kind != "narration":
                raise ComfyError("Falta el audio maestro.")
            shots = list(row.shots)
            assets = {row.audio_asset_id: (audio, "audio")}
            for shot in shots:
                if shot.get("clip_filename"):
                    continue
                asset = session.get(Asset, shot.get("image_asset_id"))
                if not asset or asset.kind != "image":
                    raise ComfyError("Falta una imagen del guion narrado.")
                assets[asset.id] = (asset, "image")
            _update(video_id, state="rendering", progress=1)
            published = {}
            for idx, (asset_id, (asset, kind)) in enumerate(assets.items()):
                path = asset_path(get_settings(), asset)
                if not path.is_file():
                    raise ComfyError("Falta un recurso original de la narración.")
                _publish(client, path, kind, asset.sha256)
                published[asset_id] = asset.sha256
                _update(video_id, progress=min(18, round((idx + 1) * 18 / len(assets))))
            manifest = {
                "id": video_id,
                "audio_id": published[row.audio_asset_id],
                "aspect_ratio": row.aspect_ratio,
                "shots": [
                    {**{
                        "start_seconds": shot["start_seconds"],
                        "end_seconds": shot["end_seconds"],
                        "motion": shot.get("motion", "zoom_in"),
                    }, **(
                        {"clip_filename": shot["clip_filename"], "clip_subfolder": shot.get("clip_subfolder", "")}
                        if shot.get("clip_filename")
                        else {"image_id": published[shot["image_asset_id"]]}
                    )}
                    for shot in shots
                ],
            }
        result = client.request("POST", API + "/jobs", json=manifest).json()
        if result.get("id") != video_id:
            raise ComfyError("El servidor remoto no confirmó el montaje.")
        for _ in range(1800):
            result = client.get(API + "/jobs/" + video_id)
            state = result.get("state")
            _update(video_id, progress=max(18, int(result.get("progress", 0))))
            if state == "completed":
                break
            if state == "failed":
                raise ComfyError(str(result.get("error") or "Falló la unión remota."))
            sleep(2)
        else:
            raise ComfyError("Se agotó el tiempo de espera del montaje remoto. Consulta RunPod/Colab.")
        settings = get_settings()
        output = settings.exports_dir / ("narrated-" + video_id + ".mp4")
        partial = settings.tmp_dir / ("narrated-" + video_id + ".download")
        try:
            with client.client.stream("GET", API + "/jobs/" + video_id + "/file", timeout=None) as stream:
                if stream.status_code != 200:
                    raise ComfyError("El servidor remoto no permitió descargar el MP4 terminado.")
                with partial.open("wb") as destination:
                    for part in stream.iter_bytes(chunk_size=1024 * 1024):
                        destination.write(part)
            if partial.stat().st_size < 1024:
                raise ComfyError("El MP4 remoto está incompleto.")
            os.replace(partial, output)
        finally:
            partial.unlink(missing_ok=True)
        _update(video_id, progress=100, state="completed",
                result_path=output.relative_to(settings.resolved_data_dir).as_posix())
    except (ComfyError, httpx.HTTPError, OSError, KeyError, ValueError) as exc:
        _update(video_id, state="failed", error=str(exc) if isinstance(exc, ComfyError) else
                "No se pudo completar la unión remota. Revisa la conexión y el log del gateway.")
    except Exception:
        _update(video_id, state="failed", error="Falló el montaje remoto. Consulta el log de Studio.")
    finally:
        if client:
            client.close()


def start_remote_video(video_id: str):
    Thread(target=_export, args=(video_id,), name="narration-remote-"+video_id[:8], daemon=True).start()
