"""Validate actual decoded media before publishing a completed Flow job."""
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

from frutinovelas.config import get_settings
from frutinovelas.services.assets import _probe_image, store_image
from frutinovelas.services.flow_transport import FlowError, flow_dir


def digest_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_ratio(width, height, ratio):
    a, b = map(float, ratio.split(":"))
    if abs(width / height - a / b) > 0.025:
        raise FlowError(f"El archivo no tiene el formato solicitado ({ratio}).")


def probe_video(path):
    settings = get_settings()
    with path.open("rb") as stream:
        if stream.read(12)[4:8] != b"ftyp":
            raise FlowError("El resultado debe ser un MP4 real.")
    try:
        r = subprocess.run([settings.ffprobe_path, "-v", "error", "-protocol_whitelist", "file,pipe",  # noqa: S603 -- local executable config, managed path, no shell
                            "-show_streams", "-show_format", "-of", "json", str(path)],
                           capture_output=True, timeout=20, check=True)
        info = json.loads(r.stdout)
        videos = [s for s in info["streams"] if s.get("codec_type") == "video"]
        if len(videos) != 1:
            raise FlowError("Se requiere un solo flujo de video.")
        v = videos[0]
        duration = float(v.get("duration") or info["format"]["duration"])
        if not math.isfinite(duration) or not 0 < duration <= 300 or not 16 <= v["width"] <= 8192 or not 16 <= v["height"] <= 8192:
            raise FlowError("Dimensiones o duración del MP4 no válidas.")
        # ffprobe alone accepts truncated files. Decode every video frame before success.
        subprocess.run([settings.ffmpeg_path, "-v", "error", "-xerror", "-err_detect", "explode",  # noqa: S603 -- local executable config, managed path, no shell
                        "-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:v:0",
                        "-f", "null", "-"], capture_output=True, timeout=120, check=True)
        return {"width": v["width"], "height": v["height"], "duration_seconds": duration,
                "has_audio": any(s.get("codec_type") == "audio" for s in info["streams"]),
                "use_provider_audio_in_montage": False}
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        raise FlowError("MP4 ilegible o FFmpeg/FFprobe no disponible. El trabajo no se completó.") from exc


def store_result(session, job, path):
    settings = get_settings()
    sha = digest_file(path)
    if job.result_sha256:
        if sha != job.result_sha256:
            raise FlowError("Este trabajo ya tiene otro resultado. Crea una nueva versión.")
    if job.kind == "image":
        probe = _probe_image(path, settings.max_image_side)
        check_ratio(probe.width, probe.height, job.snapshot["aspect_ratio"])
        with path.open("rb") as stream:
            asset = store_image(session, settings, stream, f"Flow-{job.id}.png")
        job.result_asset_id = asset.id
        job.result_path, job.result_mime = asset.rel_path, asset.mime
        job.result_metadata = {"width": probe.width, "height": probe.height}
    else:
        metadata = probe_video(path)
        check_ratio(metadata["width"], metadata["height"], job.snapshot["aspect_ratio"])
        destination = flow_dir() / "results" / (job.id + ".mp4")
        destination.parent.mkdir(exist_ok=True)
        if destination.exists() and digest_file(destination) != sha:
            raise FlowError("Hay un archivo diferente para esta versión. Se conserva el original.")
        os.replace(path, destination)
        job.result_path = destination.relative_to(settings.resolved_data_dir).as_posix()
        job.result_mime = "video/mp4"
        job.result_metadata = metadata
    job.result_sha256 = sha


def verified_path(job):
    base = get_settings().resolved_data_dir
    path = (base / (job.result_path or "")).resolve()
    if base not in path.parents or not path.is_file() or digest_file(path) != job.result_sha256:
        raise FlowError("El archivo de salida falta o cambió. Recupera el resultado antes de continuar.")
    return path
