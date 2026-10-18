"""Short managed audio originals and deterministic PCM copies for H3.

PCM WAV is decoded with the standard library. Other accepted audio containers
need the FFmpeg/FFprobe executables already configured by Studio. Neither a
filename nor a MIME supplied by a client is treated as proof of audio content.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import uuid
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from frutinovelas.config import Settings
from frutinovelas.models import Asset
from frutinovelas.services.assets import CHUNK, AssetError, asset_path

MAX_AUDIO_SECONDS = 15.0
PREPARED_SAMPLE_RATE = 32000
FORMATS = "wav,mp3,aac,flac,ogg,mov,matroska,webm"


@dataclass(frozen=True)
class AudioInfo:
    mime: str
    extension: str
    duration_seconds: float


class _NeedsDecoder(Exception):
    pass


def _read_pcm(path: Path) -> tuple[wave._wave_params, bytes]:
    try:
        with wave.open(str(path), "rb") as source:
            params = source.getparams()
            if params.comptype != "NONE":
                raise _NeedsDecoder
            if params.nchannels not in (1, 2) or params.sampwidth not in (1, 2, 3, 4):
                raise AssetError("Usa un audio mono o estéreo, con muestras PCM de 8, 16, 24 o 32 bits.")
            if not 8000 <= params.framerate <= 192000:
                raise AssetError("La frecuencia del audio debe estar entre 8 y 192 kHz.")
            duration = params.nframes / params.framerate
            if not 0 < duration <= MAX_AUDIO_SECONDS:
                raise AssetError("El audio debe tener contenido y durar como máximo 15 segundos.")
            data = source.readframes(params.nframes + 1)
            if len(data) != params.nframes * params.nchannels * params.sampwidth:
                raise AssetError("El archivo WAV está incompleto o dañado.")
            return params, data
    except (wave.Error, EOFError) as exc:
        raise _NeedsDecoder from exc


def _pcm16(data: bytes, width: int) -> array:
    if width == 1:
        return array("h", ((value - 128) << 8 for value in data))
    if width in (2, 4):
        samples = array("h" if width == 2 else "i")
        samples.frombytes(data)
        if sys.byteorder != "little":
            samples.byteswap()
        return samples if width == 2 else array("h", (sample >> 16 for sample in samples))
    return array(
        "h", (int.from_bytes(data[index : index + 3], "little", signed=True) >> 8 for index in range(0, len(data), 3))
    )


def _write_pcm(source: Path, destination: Path) -> AudioInfo:
    params, data = _read_pcm(source)
    samples = _pcm16(data, params.sampwidth)
    if params.framerate != PREPARED_SAMPLE_RATE:
        # Bounded by the 15-second, two-channel limit. Keep channel identity.
        converted = array("h")
        frames = max(1, round(params.nframes * PREPARED_SAMPLE_RATE / params.framerate))
        for frame in range(frames):
            position = frame * params.framerate / PREPARED_SAMPLE_RATE
            before = min(int(position), params.nframes - 1)
            after = min(before + 1, params.nframes - 1)
            fraction = position - before
            for channel in range(params.nchannels):
                left = samples[before * params.nchannels + channel]
                right = samples[after * params.nchannels + channel]
                converted.append(round(left + (right - left) * fraction))
        samples = converted
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(params.nchannels)
        output.setsampwidth(2)
        output.setframerate(PREPARED_SAMPLE_RATE)
        output.writeframes(samples.tobytes())
    return AudioInfo("audio/wav", ".wav", params.nframes / params.framerate)


def _executable(value: str) -> str:
    executable = shutil.which(value)
    if not executable:
        raise AssetError("Para MP3, M4A y otros formatos instala FFmpeg y FFprobe, o sube un WAV PCM.")
    return executable


def _run(command: list[str], timeout: float) -> bytes:
    try:
        result = subprocess.run(  # noqa: S603 - fixed commands and managed paths, never a shell
            command, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise AssetError("El audio tardó demasiado en procesarse. Usa un archivo corto WAV PCM.") from exc
    except OSError as exc:
        raise AssetError("No se pudo iniciar FFmpeg o FFprobe. Comprueba su instalación.") from exc
    if result.returncode:
        raise AssetError("El archivo no es un audio válido o está dañado. Exporta otra copia e inténtalo de nuevo.")
    if len(result.stdout) > 100000:
        raise AssetError("El archivo contiene demasiadas pistas o metadatos de audio.")
    return result.stdout


def _decode_audio(settings: Settings, source: Path, destination: Path) -> AudioInfo:
    ffprobe, ffmpeg = _executable(settings.ffprobe_path), _executable(settings.ffmpeg_path)
    raw = _run(
        [
            ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS,
            "-probesize", "5000000", "-analyzeduration", "5000000", "-show_entries",
            "format=format_name:stream=codec_type,channels:stream_disposition=attached_pic", "-of", "json", str(source),
        ],
        15,
    )
    try:
        metadata = json.loads(raw)
        streams = metadata["streams"]
        audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
        has_video = any(
            stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic")
            for stream in streams
        )
        if len(audio) != 1 or has_video:
            raise AssetError("Sube un archivo con una sola pista de audio, sin video.")
        channels = int(audio[0]["channels"])
        if channels not in (1, 2):
            raise AssetError("La voz de referencia debe ser mono o estéreo.")
        formats = set(metadata["format"]["format_name"].split(","))
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, AssetError):
            raise
        raise AssetError("No se pudo comprobar la pista de audio del archivo.") from exc
    types = [
        ("wav", "audio/wav", ".wav"), ("mp3", "audio/mpeg", ".mp3"), ("aac", "audio/aac", ".aac"),
        ("flac", "audio/flac", ".flac"), ("ogg", "audio/ogg", ".ogg"),
        ("mov", "audio/mp4", ".m4a"), ("matroska", "audio/webm", ".webm"),
    ]
    kind = next(((mime, extension) for fmt, mime, extension in types if fmt in formats), None)
    if kind is None:
        raise AssetError("Formato de audio no admitido. Usa WAV, MP3, M4A, AAC, FLAC, OGG o WebM.")
    _run(
        [
            ffmpeg, "-nostdin", "-v", "error", "-xerror", "-protocol_whitelist", "file,pipe",
            "-format_whitelist", FORMATS, "-i", str(source), "-map", "0:a:0", "-vn", "-ac", str(channels),
            "-ar", str(PREPARED_SAMPLE_RATE), "-c:a", "pcm_s16le", "-t", "15.01", "-f", "wav", "-y", str(destination),
        ],
        30,
    )
    try:
        params, _data = _read_pcm(destination)
    except _NeedsDecoder as exc:
        raise AssetError("FFmpeg no produjo una copia WAV válida.") from exc
    return AudioInfo(*kind, params.nframes / params.framerate)


def _prepare(settings: Settings, source: Path, destination: Path) -> AudioInfo:
    with source.open("rb") as stream:
        header = stream.read(16)
    if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        try:
            return _write_pcm(source, destination)
        except _NeedsDecoder:
            pass
    elif not (
        header.startswith((b"ID3", b"fLaC", b"OggS", b"\x1aE\xdf\xa3", b"RF64", b"RIFX"))
        or header[4:8] == b"ftyp"
        or (len(header) > 1 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0)
    ):
        raise AssetError("El archivo no es un audio válido. La extensión por sí sola no es suficiente.")
    return _decode_audio(settings, source, destination)


def _prepared_path(settings: Settings, sha256: str) -> Path:
    return settings.cache_dir / "audio" / f"{sha256}-{PREPARED_SAMPLE_RATE}-pcm16.wav"


def _save_prepared(prepared: Path, cached: Path) -> None:
    fingerprint = hashlib.sha256(prepared.read_bytes()).hexdigest()
    marker = cached.with_suffix(".sha256")
    temporary = marker.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(fingerprint, encoding="ascii")
        os.replace(prepared, cached)
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)


def _cached_valid(cached: Path, duration: float) -> bool:
    try:
        marker = cached.with_suffix(".sha256").read_text(encoding="ascii").strip()
        if marker != hashlib.sha256(cached.read_bytes()).hexdigest():
            return False
        params, _data = _read_pcm(cached)
        return (
            params.framerate == PREPARED_SAMPLE_RATE
            and params.sampwidth == 2
            and abs(params.nframes / params.framerate - duration) <= 1 / PREPARED_SAMPLE_RATE
        )
    except (OSError, UnicodeError, AssetError, _NeedsDecoder):
        return False


def store_audio(session: Session, settings: Settings, stream: BinaryIO, original_name: str) -> Asset:
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = settings.tmp_dir / f"audio-upload-{uuid.uuid4().hex}"
    prepared = tmp.with_suffix(".wav")
    digest, size = hashlib.sha256(), 0
    try:
        with tmp.open("wb") as output:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise AssetError(f"El audio supera el límite de {settings.max_upload_mb} MB.")
                digest.update(chunk)
                output.write(chunk)
        if not size:
            raise AssetError("El archivo de audio está vacío.")
        sha256 = digest.hexdigest()
        existing = session.scalar(select(Asset).where(Asset.sha256 == sha256))
        if existing is not None:
            if existing.kind != "audio":
                raise AssetError("El archivo no es un audio válido.")
            original = asset_path(settings, existing)
            if original.is_file() and original.stat().st_size == size:
                with original.open("rb") as saved:
                    if hashlib.file_digest(saved, "sha256").hexdigest() == sha256:
                        return existing
        info = _prepare(settings, tmp, prepared)
        relative = Path("assets") / sha256[:2] / f"{sha256}{info.extension}"
        destination = settings.resolved_data_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, destination)
        cached = _prepared_path(settings, sha256)
        cached.parent.mkdir(parents=True, exist_ok=True)
        _save_prepared(prepared, cached)
        if existing is not None:
            existing.rel_path = relative.as_posix()
            existing.duration_seconds = info.duration_seconds
            session.flush()
            return existing
        asset = Asset(
            kind="audio", rel_path=relative.as_posix(), sha256=sha256, size_bytes=size,
            mime=info.mime, width=None, height=None, duration_seconds=info.duration_seconds,
            original_name=(original_name or "audio").replace("\\", "/").rsplit("/", 1)[-1][:300],
        )
        session.add(asset)
        session.flush()
        return asset
    finally:
        tmp.unlink(missing_ok=True)
        prepared.unlink(missing_ok=True)


def prepare_audio_path(settings: Settings, asset: Asset) -> Path:
    """Return a managed 32 kHz PCM16 WAV without changing the original asset."""
    if asset.kind != "audio":
        raise AssetError("La guía seleccionada no es un archivo de audio.")
    if not asset.duration_seconds or not math.isfinite(asset.duration_seconds) or not 0 < asset.duration_seconds <= MAX_AUDIO_SECONDS:
        raise AssetError("La duración guardada del audio no es válida. Vuelve a subirlo.")
    source = asset_path(settings, asset)
    if not source.is_file():
        raise AssetError("Falta el archivo de audio en el almacenamiento.")
    cached = _prepared_path(settings, asset.sha256)
    if _cached_valid(cached, asset.duration_seconds):
        return cached
    cached.parent.mkdir(parents=True, exist_ok=True)
    temporary = cached.with_suffix(f".{uuid.uuid4().hex}.wav")
    try:
        info = _prepare(settings, source, temporary)
        if abs(info.duration_seconds - asset.duration_seconds) > 1 / PREPARED_SAMPLE_RATE:
            raise AssetError("La duración del archivo de audio cambió. Vuelve a subirlo.")
        _save_prepared(temporary, cached)
    finally:
        temporary.unlink(missing_ok=True)
    return cached
