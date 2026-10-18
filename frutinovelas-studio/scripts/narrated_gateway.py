"""Authenticated, server-side FFmpeg assembly for RunPod and Colab.

Only pre-uploaded, hash-addressed images/audio or files confined to ComfyUI's
output directory can be used. No client-supplied paths or shell commands.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from aiohttp import web
from PIL import Image, UnidentifiedImageError

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_SECONDS = 300
MAX_SHOTS = 90
CHUNK = 1024 * 1024
SHA = re.compile(r"^[0-9a-f]{64}$")
CLIP_NAME = re.compile(r"^[A-Za-z0-9_. -]{1,200}\.mp4$", re.I)
CLIP_FOLDER = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$")
MOTIONS = frozenset(("zoom_in", "zoom_out", "pan_left", "pan_right", "still"))
EXTENSIONS = {
    "image": (".png", ".jpg", ".webp"),
    "audio": (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".webm"),
}


class AssemblyError(ValueError):
    pass


def run_ffmpeg(args: list[str], timeout: int = 600) -> None:
    try:
        process = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AssemblyError("No se pudo completar el montaje remoto con FFmpeg.") from exc
    if process.returncode:
        raise AssemblyError("FFmpeg falló en una toma o al unirlas; revisa las imágenes y clips.")


def probe(path: Path) -> dict:
    binary = shutil.which("ffprobe")
    if not binary:
        raise AssemblyError("Falta FFprobe en el servidor de ComfyUI.")
    try:
        process = subprocess.run(
            [binary, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
             "-of", "json", str(path)],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=25, check=True,
        )
        result = json.loads(process.stdout)
        return result
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
        raise AssemblyError("El servidor no pudo validar un audio o clip.") from exc


def audio_duration(path: Path) -> float:
    info = probe(path)
    streams = info.get("streams", [])
    if len([s for s in streams if s.get("codec_type") == "audio"]) != 1 or any(
        s.get("codec_type") == "video" for s in streams
    ):
        raise AssemblyError("La narración debe contener una sola pista de audio y ningún video.")
    try:
        duration = float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AssemblyError("El audio no tiene una duración reconocible.") from exc
    if not math.isfinite(duration) or not 0 < duration <= MAX_SECONDS:
        raise AssemblyError("El audio debe durar hasta cinco minutos.")
    return duration


def image_extension(path: Path) -> str:
    try:
        with Image.open(path) as picture:
            picture.verify()
        with Image.open(path) as picture:
            fmt = picture.format
            width, height = picture.size
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise AssemblyError("La imagen subida no es válida.") from exc
    if not 16 <= width <= 8192 or not 16 <= height <= 8192:
        raise AssemblyError("La imagen supera los límites permitidos.")
    return {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(fmt) or _invalid_image()


def _invalid_image():
    raise AssemblyError("Solo se permiten imágenes PNG, JPEG o WebP.")


def audio_extension(path: Path) -> str:
    # Require actual FFprobe demuxer detection; untrusted filename is ignored.
    audio_duration(path)
    args = [shutil.which("ffprobe"), "-v", "error", "-show_entries", "format=format_name",
            "-of", "json", str(path)]
    try:
        raw = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=True)
        formats = set(json.loads(raw.stdout)["format"]["format_name"].split(","))
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise AssemblyError("El formato del audio es desconocido.") from exc
    for fmt, extension in (("wav", ".wav"), ("mp3", ".mp3"), ("mov", ".m4a"),
                           ("aac", ".aac"), ("flac", ".flac"), ("ogg", ".ogg"),
                           ("matroska", ".webm")):
        if fmt in formats:
            return extension
    raise AssemblyError("Formato de audio no admitido.")


def motion_filter(motion: str, seconds: float, width: int, height: int) -> str:
    frames = max(1, round(seconds * 24))
    zoom = {
        "zoom_in": f"1+0.10*on/{frames}",
        "zoom_out": f"1.10-0.10*on/{frames}",
        "pan_left": "1.10",
        "pan_right": "1.10",
        "still": "1",
    }[motion]
    x = "iw/2-(iw/zoom/2)"
    if motion == "pan_left":
        x = f"(iw-iw/zoom)*(1-on/{frames})"
    elif motion == "pan_right":
        x = f"(iw-iw/zoom)*on/{frames}"
    return (f"scale={width*2}:{height*2}:force_original_aspect_ratio=increase,"
            f"crop={width*2}:{height*2},zoompan=z='{zoom}':x='{x}':"
            f"y='ih/2-ih/zoom/2':d={frames}:s={width}x{height}:fps=24,"
            "format=yuv420p")


class NarrationStore:
    def __init__(self, root: Path, comfy_output: Path | None = None):
        self.root = root.resolve()
        self.assets = self.root / "assets"
        self.jobs = self.root / "jobs"
        self.output = self.root / "exports"
        self.comfy_output = comfy_output.resolve() if comfy_output else None
        for folder in (self.assets, self.jobs, self.output):
            folder.mkdir(parents=True, exist_ok=True)
        self.lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()

    def asset(self, sha: str, kind: str) -> Path:
        if not isinstance(sha, str) or not SHA.fullmatch(sha) or kind not in EXTENSIONS:
            raise AssemblyError("Referencia de recurso inválida.")
        for extension in EXTENSIONS[kind]:
            path = self.assets / (sha + extension)
            if path.is_file():
                return path
        raise AssemblyError("El recurso no está disponible en el servidor remoto.")

    def clip(self, filename: str, folder: str) -> Path:
        if not self.comfy_output:
            raise AssemblyError("No se configuró el directorio de salida de ComfyUI.")
        if not isinstance(filename, str) or not CLIP_NAME.fullmatch(filename) or ".." in filename:
            raise AssemblyError("Nombre de clip remoto no permitido.")
        if not isinstance(folder, str) or (folder and (not CLIP_FOLDER.fullmatch(folder) or ".." in folder)):
            raise AssemblyError("Subcarpeta de clip inválida.")
        base = self.comfy_output
        path = (base / folder / filename).resolve()
        if base not in path.parents or not path.is_file() or path.is_symlink():
            raise AssemblyError("El clip no existe en la salida de ComfyUI.")
        return path

    def filename(self, job_id: str, suffix: str = ".json") -> Path:
        try:
            normalized = str(uuid.UUID(job_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise AssemblyError("ID de montaje inválido.") from exc
        if normalized != job_id:
            raise AssemblyError("El ID debe ser un UUID normalizado.")
        return self.jobs / (job_id + suffix)

    def read(self, job_id: str) -> dict | None:
        path = self.filename(job_id)
        if not path.is_file():
            return None
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry["state"] in ("queued", "rendering"):
            # As another worker might still be generating, this branch is used only
            # at gateway startup, not on every request.
            pass
        return entry

    def save(self, row: dict) -> None:
        path = self.filename(row["id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def recover(self):
        for file in self.jobs.glob("*.json"):
            try:
                row = json.loads(file.read_text(encoding="utf-8"))
                if row.get("state") in ("queued", "rendering"):
                    row["state"] = "failed"
                    row["error"] = "El servidor remoto se reinició; vuelve a exportar con otro ID."
                    self.save(row)
            except (OSError, ValueError, KeyError):
                continue

    def validate(self, data: dict) -> tuple[Path, list[dict], float]:
        if not isinstance(data, dict):
            raise AssemblyError("El manifiesto no es válido.")
        job_id = data.get("id")
        self.filename(job_id)
        audio = self.asset(data.get("audio_id"), "audio")
        duration = audio_duration(audio)
        if data.get("aspect_ratio") not in ("9:16", "16:9"):
            raise AssemblyError("Formato de video no admitido.")
        shots = data.get("shots")
        if not isinstance(shots, list) or not 1 <= len(shots) <= MAX_SHOTS:
            raise AssemblyError("El montaje necesita entre 1 y 90 tomas.")
        previous = 0.0
        for i, shot in enumerate(shots):
            if not isinstance(shot, dict):
                raise AssemblyError("Una toma no tiene formato válido.")
            start, end, motion = shot.get("start_seconds"), shot.get("end_seconds"), shot.get("motion", "zoom_in")
            if not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in (start, end)):
                raise AssemblyError(f"Marcas de tiempo inválidas en la toma {i+1}.")
            if start < 0 or end-start < 0.05 or end > duration+0.06 or abs(start-previous) > 0.06:
                raise AssemblyError(f"La toma {i+1} no coincide con la cronología del audio.")
            if motion not in MOTIONS:
                raise AssemblyError("Movimiento de cámara no permitido.")
            if shot.get("clip_filename"):
                path = self.clip(shot["clip_filename"], shot.get("clip_subfolder", ""))
                if not any(stream.get("codec_type") == "video" for stream in probe(path).get("streams", [])):
                    raise AssemblyError("El archivo H3 no contiene video.")
            else:
                self.asset(shot.get("image_id"), "image")
            previous = end
        if abs(previous-duration) > 0.06:
            raise AssemblyError("Faltan tomas para cubrir toda la narración.")
        return audio, shots, duration

    def assemble(self, data: dict) -> None:
        job_id = data["id"]
        row = self.read(job_id)
        row["state"] = "rendering"
        self.save(row)
        tmpdir = self.root / ("working-" + job_id)
        tmpdir.mkdir(mode=0o700, exist_ok=True)
        try:
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise AssemblyError("Instala FFmpeg en RunPod o Colab.")
            audio, shots, duration = self.validate(data)
            width, height = (576, 1024) if data["aspect_ratio"] == "9:16" else (1024, 576)
            clips: list[Path] = []
            for i, shot in enumerate(shots):
                seconds = float(shot["end_seconds"]) - float(shot["start_seconds"])
                frames = max(1, round(seconds * 24))
                clip = tmpdir / f"{i:03}.mp4"
                args = [ffmpeg, "-y", "-nostdin", "-v", "error"]
                if shot.get("clip_filename"):
                    path = self.clip(shot["clip_filename"], shot.get("clip_subfolder", ""))
                    args += ["-i", str(path), "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                             f"crop={width}:{height},fps=24,tpad=stop_mode=clone:stop_duration={seconds:.5f},"
                             "format=yuv420p"]
                else:
                    path = self.asset(shot["image_id"], "image")
                    args += ["-loop", "1", "-framerate", "24", "-i", str(path),
                             "-vf", motion_filter(shot["motion"], seconds, width, height)]
                args += ["-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "veryfast",
                         "-crf", "21", "-pix_fmt", "yuv420p", str(clip)]
                run_ffmpeg(args, timeout=180)
                clips.append(clip)
                row["progress"] = round((i + 1) * 90 / len(shots))
                self.save(row)
            manifest = tmpdir / "concat.txt"
            # Names are generated by our server, not by user input.
            manifest.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding="utf-8")
            partial = tmpdir / "complete.mp4"
            run_ffmpeg([ffmpeg, "-y", "-nostdin", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", str(manifest), "-i", str(audio),
                        "-map", "0:v:0", "-map", "1:a:0",
                        "-vf", "fps=24,tpad=stop_mode=clone:stop_duration=1,format=yuv420p",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-c:a", "aac", "-b:a", "192k", "-t", f"{duration:.5f}",
                        "-movflags", "+faststart", str(partial)], timeout=900)
            output = self.output / (job_id + ".mp4")
            os.replace(partial, output)
            row["state"] = "completed"
            row["progress"] = 100
            self.save(row)
        except Exception as exc:
            row["state"] = "failed"
            row["error"] = str(exc) if isinstance(exc, AssemblyError) else "Error del montaje remoto; consulta el log del gateway."
            self.save(row)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def submit(self, data: dict) -> dict:
        # Validate the job *before* reserving the ID.
        await asyncio.to_thread(self.validate, data)
        signature = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        async with self.lock:
            existing = self.read(data["id"])
            if existing is not None:
                if existing.get("signature") != signature:
                    raise web.HTTPConflict(text="Ese ID pertenece a otro montaje.")
                return self.public(existing)
            row = {"id": data["id"], "signature": signature, "state": "queued", "progress": 0, "error": ""}
            self.save(row)
            task = asyncio.create_task(asyncio.to_thread(self.assemble, data))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            return self.public(row)

    @staticmethod
    def public(row: dict) -> dict:
        return {name: row[name] for name in ("id", "state", "progress", "error")}


def register_narration_routes(app: web.Application, root: Path, comfy_output: Path | None = None) -> None:
    store = NarrationStore(root, comfy_output)
    store.recover()

    async def capabilities(_request):
        return web.json_response({"supported": True, "engine": "remote-ffmpeg", "max_seconds": MAX_SECONDS,
                                  "max_shots": MAX_SHOTS, "ffmpeg": bool(shutil.which("ffmpeg"))})

    async def upload(request):
        reader = await request.multipart()
        kind: str | None = None
        temp = store.root / ("upload-" + uuid.uuid4().hex)
        sha = hashlib.sha256()
        size = 0
        try:
            async for part in reader:
                if part.name == "kind":
                    kind = (await part.text())[:20]
                elif part.name == "file":
                    with temp.open("wb") as stream:
                        while chunk := await part.read_chunk(size=CHUNK):
                            size += len(chunk)
                            if size > MAX_FILE_BYTES:
                                raise web.HTTPRequestEntityTooLarge(max_size=MAX_FILE_BYTES, actual_size=size)
                            sha.update(chunk)
                            stream.write(chunk)
            if kind not in EXTENSIONS or size == 0:
                raise AssemblyError("Archivo o tipo no válido.")
            extension = await asyncio.to_thread(image_extension if kind == "image" else audio_extension, temp)
            dest = store.assets / (sha.hexdigest() + extension)
            os.replace(temp, dest)
            return web.json_response({"id": sha.hexdigest(), "kind": kind, "size": size})
        except AssemblyError as exc:
            raise web.HTTPUnprocessableEntity(text=str(exc)) from exc
        finally:
            temp.unlink(missing_ok=True)

    async def create(request):
        try:
            data = await request.json()
            return web.json_response(await store.submit(data), status=202)
        except (AssemblyError, KeyError, TypeError, ValueError) as exc:
            raise web.HTTPUnprocessableEntity(text=str(exc)) from exc

    async def status(request):
        try:
            row = store.read(request.match_info["id"])
        except AssemblyError:
            raise web.HTTPNotFound()
        if not row:
            raise web.HTTPNotFound()
        return web.json_response(store.public(row))

    async def download(request):
        job_id = request.match_info["id"]
        try:
            row = store.read(job_id)
        except AssemblyError:
            raise web.HTTPNotFound()
        if not row or row["state"] != "completed":
            raise web.HTTPNotFound()
        path = store.output / (job_id + ".mp4")
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Content-Type": "video/mp4"})

    app.router.add_get("/frutinovelas/narration/capabilities", capabilities)
    app.router.add_post("/frutinovelas/narration/assets", upload)
    app.router.add_post("/frutinovelas/narration/jobs", create)
    app.router.add_get("/frutinovelas/narration/jobs/{id}", status)
    app.router.add_get("/frutinovelas/narration/jobs/{id}/file", download)
