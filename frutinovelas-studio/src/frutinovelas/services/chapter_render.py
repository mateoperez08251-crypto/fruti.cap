"""Explicit opt-in chapter runs: saved scene plans -> serial images/videos -> one MP4."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from frutinovelas.config import get_settings
from frutinovelas.models import Chapter, ChapterRender, ComfyConnection, GenerationJob
from frutinovelas.services.comfy import ComfyClient, ComfyError, identity_key
from frutinovelas.services.generation import connection_token
from frutinovelas.services.image_generation import (
    EDIT_WORKFLOW,
    T2I_WORKFLOW,
    enqueue_image,
    graph_contract,
    video_request_id,
)
from frutinovelas.services.scenes import list_scene_outputs


def public_run(run):
    return dict(
        id=run.id,
        chapter_id=run.chapter_id,
        state=run.state,
        error=run.error,
        scenes=run.snapshot["scenes"],
        created_at=run.created_at,
        result_url=f"/api/v1/chapter-renders/{run.id}/content" if run.result_path else None,
    )


def ffmpeg_tools():
    ffmpeg = shutil.which(get_settings().ffmpeg_path)
    probe = shutil.which(
        str(
            Path(ffmpeg or get_settings().ffmpeg_path).with_name(
                "ffprobe" + (".exe" if str(ffmpeg).endswith(".exe") else "")
            )
        )
    )
    if not ffmpeg or not probe:
        raise ComfyError("El montaje automático necesita FFmpeg y ffprobe instalados en este PC.")
    return ffmpeg, probe


def create_run(session, chapter_id, expected_revision, revisions, request_id, client_factory=ComfyClient):
    existing = session.get(ChapterRender, request_id)
    if existing:
        if (
            existing.chapter_id != chapter_id
            or existing.snapshot["chapter_revision"] != expected_revision
            or existing.snapshot["requested_revisions"] != revisions
        ):
            raise ComfyError("Ese ID pertenece a otra solicitud de capítulo.")
        return existing
    chapter = session.get(Chapter, chapter_id)
    if not chapter:
        raise ComfyError("Capítulo no encontrado.")
    if chapter.revision != expected_revision:
        raise ComfyError("El guion o la continuidad cambiaron. Actualiza el capítulo antes de generar.")
    scenes = list_scene_outputs(session, chapter_id)
    if not scenes or {s.id: s.revision for s in scenes} != revisions:
        raise ComfyError("Actualiza la lista de escenas antes de iniciar el capítulo automático.")
    ffmpeg_tools()
    for scene in scenes:
        if (
            not scene.parameters.get("image_prompt", "").strip()
            or not scene.prompt.strip()
            or not 4 <= scene.duration_seconds <= 15
        ):
            raise ComfyError(f"Prepara y guarda ambos prompts y 4–15 segundos en «{scene.title}».")
        if session.scalar(select(GenerationJob.id).where(GenerationJob.active_scene_id == scene.id)):
            raise ComfyError(
                "Una escena ya tiene una generación activa. Espera antes de iniciar el capítulo."
            )
    connection = session.get(ComfyConnection, "default")
    if not connection:
        raise ComfyError("Configura primero la conexión con ComfyUI.")
    url, token = connection.url, connection_token(connection)
    saved_identity_key = identity_key(connection.identity)
    manifest = []
    kinds = set()
    for scene in scenes:
        image_id = str(uuid5(UUID(request_id), "image:" + scene.id))
        manifest.append(
            dict(
                scene_id=scene.id,
                revision=scene.revision,
                title=scene.title,
                image_job_id=image_id,
                video_job_id=video_request_id(image_id),
            )
        )
        kinds.add(bool(scene.parameters.get("cast")))
    session.rollback()
    client = client_factory(url, token)
    try:
        identity = client.get("/frutinovelas/identity")
        if identity_key(identity) != saved_identity_key:
            raise ComfyError(
                "La conexión guardada cambió. Usa Guardar y comprobar antes de iniciar el capítulo."
            )
        for edit in kinds:
            filename = EDIT_WORKFLOW if edit else T2I_WORKFLOW
            expected = (identity.get("workflows") or {}).get(filename)
            if not expected:
                raise ComfyError("Falta el flujo Qwen necesario para una escena: " + filename)
            raw = client.request("GET", "/frutinovelas/workflows/" + filename).content
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ComfyError("El hash de un flujo Qwen no coincide con el servidor.")
            graph_contract(json.loads(raw), edit)
    finally:
        client.close()
    session.expire_all()
    fresh = session.get(Chapter, chapter_id)
    if (
        fresh.revision != expected_revision
        or {s.id: s.revision for s in list_scene_outputs(session, chapter_id)} != revisions
    ):
        raise ComfyError("El capítulo cambió durante la comprobación. No se inició ninguna generación.")
    run = ChapterRender(
        id=request_id,
        chapter_id=chapter_id,
        active_chapter_id=chapter_id,
        state="queued",
        snapshot=dict(
            scenes=manifest,
            chapter_revision=expected_revision,
            requested_revisions=revisions,
            runtime_key=identity_key(identity),
            url=url,
        ),
    )
    session.add(run)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.get(ChapterRender, request_id)
        if (
            existing
            and existing.chapter_id == chapter_id
            and existing.snapshot["requested_revisions"] == revisions
        ):
            return existing
        raise ComfyError("Este capítulo ya tiene un proceso automático en curso.") from exc
    return run


def advance_runs(factory, stop_event, client_factory=ComfyClient):
    """Called only by the single worker holding its OS lock. Each call advances one step."""
    with factory() as session:
        run = session.scalar(
            select(ChapterRender)
            .where(ChapterRender.active_chapter_id.is_not(None))
            .order_by(ChapterRender.created_at)
            .limit(1)
        )
        if not run or stop_event.is_set():
            return
        id, snapshot = run.id, dict(run.snapshot)
        try:
            chapter = session.get(Chapter, run.chapter_id)
            if not chapter or chapter.revision != snapshot["chapter_revision"]:
                raise ComfyError("El guion o la continuidad cambiaron. Se detuvo la continuación automática.")
            current = {s.id: s.revision for s in list_scene_outputs(session, run.chapter_id)}
            if list(current) != [e["scene_id"] for e in snapshot["scenes"]]:
                raise ComfyError("Cambió la lista de escenas. Se detuvo el proceso.")
            for entry in snapshot["scenes"]:
                image = session.get(GenerationJob, entry["image_job_id"])
                expected = (
                    image.snapshot.get("approved_scene_revision", entry["revision"])
                    if image
                    else entry["revision"]
                )
                if current[entry["scene_id"]] != expected:
                    raise ComfyError("Cambió una escena. Se detuvo el proceso; se conservan los resultados.")
            paths = []
            for entry in snapshot["scenes"]:
                image = session.get(GenerationJob, entry["image_job_id"])
                video = session.get(GenerationJob, entry["video_job_id"])
                if image is None:
                    connection = session.get(ComfyConnection, "default")
                    if not connection or connection.url != snapshot["url"]:
                        raise ComfyError("Cambió la conexión del capítulo. Se detuvo el proceso.")
                    run.state = "generating"
                    session.commit()
                    enqueue_image(
                        session,
                        entry["scene_id"],
                        entry["revision"],
                        entry["image_job_id"],
                        client_factory,
                        auto_animate=True,
                        force_automatic=True,
                        runtime_key=snapshot["runtime_key"],
                        chapter_render_id=id,
                    )
                    return
                if image.state in ("failed", "cancelled") or image.error and image.state == "completed":
                    raise ComfyError("Una imagen necesita revisión: " + (image.error or entry["title"]))
                if image.state != "completed" or not image.snapshot.get("auto_finish_done"):
                    return
                if video is None:
                    raise ComfyError("No se pudo continuar con la animación de «" + entry["title"] + "».")
                if video.state in ("failed", "cancelled"):
                    raise ComfyError("Falló la animación de «" + entry["title"] + "»: " + video.error)
                if video.state != "completed":
                    return
                base = get_settings().resolved_data_dir
                path = (base / (video.result_path or "")).resolve()
                if base not in path.parents or not path.is_file():
                    raise ComfyError("Falta un clip del montaje: " + entry["title"])
                paths.append(path)
            run.state = "assembling"
            session.commit()
            # No SQLite transaction is held during FFmpeg.
            result = assemble(id, paths, stop_event)
            if result is None:
                return
            session.expire_all()
            run = session.get(ChapterRender, id)
            run.state, run.active_chapter_id = "completed", None
            run.result_path = result.relative_to(get_settings().resolved_data_dir).as_posix()
            session.commit()
        except Exception as exc:
            session.rollback()
            run = session.get(ChapterRender, id)
            run.state, run.active_chapter_id = "failed", None
            run.error = (
                str(exc)
                if isinstance(exc, ComfyError)
                else "No se pudo continuar el capítulo. Revisa los trabajos y el registro del programa."
            )
            session.commit()


def assemble(id, paths, stop_event):
    ffmpeg, probe = ffmpeg_tools()
    settings = get_settings()
    output = settings.exports_dir / ("chapter-" + id + ".mp4")
    partial = settings.tmp_dir / (id + "-chapter.partial.mp4")
    args = [ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error"]
    filters, streams = [], []
    for i, path in enumerate(paths):
        info = subprocess.run(  # noqa: S603 — executable configured locally; managed paths, no shell
            [probe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        metadata = json.loads(info.stdout)
        videos = [s for s in metadata["streams"] if s["codec_type"] == "video"]
        if not videos:
            raise ComfyError("Un clip no contiene video.")
        duration = float(videos[0].get("duration") or metadata["format"]["duration"])
        if not 0 < duration < 120:
            raise ComfyError("Duración de clip no compatible con el montaje.")
        args += ["-i", str(path)]
        filters.append(
            f"[{i}:v:0]scale=576:1024:force_original_aspect_ratio=decrease,pad=576:1024:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,format=yuv420p,setpts=PTS-STARTPTS[v{i}]"
        )
        if any(s["codec_type"] == "audio" for s in metadata["streams"]):
            filters.append(
                f"[{i}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=duration={duration},asetpts=PTS-STARTPTS[a{i}]"
            )
        else:
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={duration},asetpts=PTS-STARTPTS[a{i}]")
        streams.append(f"[v{i}][a{i}]")
    filters.append("".join(streams) + f"concat=n={len(paths)}:v=1:a=1[v][a]")
    args += [
        "-filter_complex_threads",
        "1",
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-threads",
        "2",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(partial),
    ]
    log_path = settings.tmp_dir / (id + "-assembly.log")
    with log_path.open("wb") as log:
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=log)  # noqa: S603 — argument list, no shell
        try:
            elapsed = 0
            while process.poll() is None:
                if stop_event.wait(0.5):
                    return None
                elapsed += 0.5
                if elapsed > 900:
                    raise ComfyError("El montaje superó el tiempo permitido.")
            if process.returncode:
                raise ComfyError("FFmpeg no pudo montar los clips. Los originales se conservan.")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    partial.replace(output)
    log_path.unlink(missing_ok=True)
    return output
