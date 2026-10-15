"""Worker H3: cola durable, una inferencia, recuperación sin repetir POST inciertos."""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from pathlib import Path

import httpx
from PIL import Image, ImageOps
from sqlalchemy import select

from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.models import Asset, GenerationJob
from frutinovelas.services.assets import AssetError, asset_path, store_image
from frutinovelas.services.comfy import ComfyClient, ComfyError, cipher, identity_key, prepare_graph
from frutinovelas.services.generation import ACTIVE, transition
from frutinovelas.services.image_generation import finish_automatic_image, graph_contract, prepare_image_graph

log = logging.getLogger(__name__)


class WorkerLock:
    """OS lock released even after a crash; works on Windows and Linux."""

    def __init__(self, path):
        self.path, self.file = path, None

    def acquire(self):
        if self.file:
            return True
        f = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            import os

            if os.name == "nt":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self.file = f
        return True

    def release(self):
        if self.file:
            self.file.close()
            self.file = None


class GenerationWorker:
    def __init__(self, factory=None, client_factory=ComfyClient):
        self.settings = get_settings()
        self.factory = factory or session_factory()
        self.client_factory = client_factory
        self.stop_event = threading.Event()
        self.thread = None
        self.current_id = None
        self.lock = WorkerLock(self.settings.resolved_data_dir / "generation_worker.lock")

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        if not self.thread or not self.thread.is_alive():
            self.lock.release()

    def run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except httpx.HTTPError:
                    self.report_error("Conexión interrumpida; esperando a RunPod.", False)
                except ComfyError as exc:
                    self.report_error(str(exc), False)
                except Exception:
                    log.exception("No se pudo procesar una generación")
                    self.report_error(
                        "No se pudo preparar o recuperar la generación. Revisa las referencias y el log.",
                        True,
                    )
                self.stop_event.wait(self.settings.worker_poll_seconds)
        finally:
            self.lock.release()

    def report_error(self, message, fatal):
        if self.current_id:
            with self.factory() as s:
                job = s.get(GenerationJob, self.current_id)
                if job and job.state in ACTIVE:
                    # Once POST /prompt may have happened, a local parsing or disk
                    # error is not proof that inference failed. Keep its reservation.
                    state = job.state
                    if fatal:
                        state = "failed" if state in ("queued", "uploading") else "unknown"
                    transition(self.factory, job.id, state, message, expected_states=(job.state,))

    def tick(self):
        self.current_id = None
        if not self.lock.acquire():
            return
        with self.factory() as session:
            automatic_id = session.scalar(
                select(GenerationJob.id)
                .where(
                    GenerationJob.kind == "image",
                    GenerationJob.state == "completed",
                    GenerationJob.snapshot["auto_finish_done"].as_boolean().is_(False),
                )
                .limit(1)
            )
        if automatic_id:
            finish_automatic_image(self.factory, automatic_id)
        self._tick_job()
        from frutinovelas.services.chapter_render import advance_runs

        advance_runs(self.factory, self.stop_event, self.client_factory)

    def _tick_job(self):
        self.current_id = None
        with self.factory() as s:
            job = s.scalar(
                select(GenerationJob)
                .where(GenerationJob.state.in_(ACTIVE))
                .order_by(GenerationJob.created_at)
                .limit(1)
            )
            if job is None:
                return
            s.expunge(job)
        self.current_id = job.id
        p = job.snapshot
        client = self.client_factory(p["url"], cipher().decrypt(job.encrypted_token.encode()).decode())
        try:
            if identity_key(client.get("/frutinovelas/identity")) != identity_key(p["identity"]):
                transition(
                    self.factory,
                    job.id,
                    "failed",
                    "Cambió la identidad del servidor. Comprueba la conexión y crea otra versión.",
                )
                return
            if job.state in ("queued", "uploading"):
                if not transition(self.factory, job.id, "uploading"):
                    return
                names = {}
                references = (
                    {str(i): c["asset_id"] for i, c in enumerate(p.get("cast", []))}
                    if job.kind == "image"
                    else {role: p.get(role + "_asset_id") for role in ("start", "end")}
                )
                for role, asset_id in references.items():
                    if self.stop_event.is_set():
                        return
                    if not asset_id:
                        continue
                    with self.factory() as s:
                        asset = s.get(Asset, asset_id)
                        if asset is None:
                            raise ValueError("Falta una imagen de referencia")
                        original = asset_path(self.settings, asset)
                    prepared = self.settings.tmp_dir / f"{job.id}-{role}.png"
                    try:
                        with Image.open(original) as im:
                            oriented = ImageOps.exif_transpose(im)
                            if job.kind == "image":
                                reference = oriented.convert("RGB")
                                reference.thumbnail((1024, 1024))
                                reference.save(prepared)
                            else:
                                ImageOps.fit(oriented.convert("RGB"), (576, 1024)).save(prepared)
                        names[role] = client.upload(prepared)
                    finally:
                        prepared.unlink(missing_ok=True)
                graph = (
                    prepare_image_graph(
                        p["graph"], p["prompt"], p.get("cast", []), p["seed"], list(names.values()), job.id
                    )
                    if job.kind == "image"
                    else prepare_graph(
                        p["graph"],
                        p["prompt"],
                        p["duration"],
                        p["seed"],
                        names["start"],
                        names.get("end"),
                        job.id,
                    )
                )
                if self.stop_event.is_set() or not transition(self.factory, job.id, "submitting"):
                    return
                try:
                    r = client.request(
                        "POST",
                        "/prompt",
                        json={
                            "prompt": graph,
                            "prompt_id": job.prompt_id,
                            "client_id": "frutinovelas-" + job.id,
                        },
                    )
                    result = r.json()
                except ComfyError as exc:
                    known_rejection = exc.status_code in (400, 401, 403, 404, 422)
                    transition(self.factory, job.id, "failed" if known_rejection else "unknown", str(exc))
                    return
                except (httpx.HTTPError, ValueError):
                    transition(
                        self.factory,
                        job.id,
                        "unknown",
                        "Recepción incierta. Se comprobará cola e historial sin reenviar.",
                    )
                    return
                pid = result.get("prompt_id") if isinstance(result, dict) else None
                if not isinstance(pid, str) or not re.fullmatch(r"[0-9a-fA-F-]{1,64}", pid):
                    transition(
                        self.factory,
                        job.id,
                        "unknown",
                        "El servidor no confirmó el ID de la generación. No se reenviará.",
                    )
                    return
                if not transition(self.factory, job.id, "waiting", prompt_id=pid):
                    return
                job.prompt_id = pid
            history = client.get("/history/" + job.prompt_id).get(job.prompt_id)
            if not history:
                queue = client.get("/queue")
                running = {str(x[1]) for x in queue.get("queue_running", []) if len(x) > 1}
                pending = {str(x[1]) for x in queue.get("queue_pending", []) if len(x) > 1}
                if job.prompt_id in running:
                    transition(self.factory, job.id, "running")
                elif job.prompt_id in pending:
                    transition(self.factory, job.id, "waiting")
                else:
                    transition(
                        self.factory,
                        job.id,
                        "unknown",
                        "No aparece en la cola ni en el historial. Comprueba RunPod antes de repetir.",
                    )
                return
            status = history.get("status", {})
            if status.get("status_str") == "error":
                transition(
                    self.factory, job.id, "failed", "ComfyUI informó un error. Revisa «fruti logs comfyui»."
                )
                return
            if not status.get("completed"):
                return
            if job.kind == "image":
                self.download_image(client, job, history)
                return
            candidates = []
            output = history.get("outputs", {}).get("20", {})
            for key in ("images", "videos", "gifs"):
                candidates.extend(output.get(key, []))
            video = next(
                (x for x in candidates if Path(x.get("filename", "")).suffix.lower() in (".mp4", ".webm")),
                None,
            )
            if video is None:
                transition(
                    self.factory,
                    job.id,
                    "failed",
                    "La generación terminó sin un video compatible en SaveVideo.",
                )
                return
            if not transition(self.factory, job.id, "downloading"):
                return
            suffix = Path(video["filename"]).suffix.lower()
            dest = self.settings.versions_dir / (job.id + suffix)
            tmp = dest.with_suffix(suffix + ".part")
            digest = hashlib.sha256()
            with client.client.stream(
                "GET", "view", params={k: video[k] for k in ("filename", "subfolder", "type") if k in video}
            ) as r:
                if r.status_code != 200:
                    raise ComfyError("No se pudo descargar el video; se reintentará recuperar el resultado.")
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes():
                        if self.stop_event.is_set():
                            return
                        digest.update(chunk)
                        f.write(chunk)
            with tmp.open("rb") as f:
                header = f.read(16)
            valid = (suffix == ".mp4" and header[4:8] == b"ftyp") or (
                suffix == ".webm" and header[:4] == b"\x1aE\xdf\xa3"
            )
            if not valid:
                transition(self.factory, job.id, "failed", "El archivo recibido no es un video válido.")
                tmp.unlink(missing_ok=True)
                return
            tmp.replace(dest)
            transition(
                self.factory,
                job.id,
                "completed",
                result_path=dest.relative_to(self.settings.resolved_data_dir).as_posix(),
                result_mime="video/mp4" if suffix == ".mp4" else "video/webm",
                result_sha256=digest.hexdigest(),
            )
        finally:
            client.close()

    def download_image(self, client, job, history):
        output, _, _ = graph_contract(job.snapshot["graph"], bool(job.snapshot.get("cast")))
        candidates = history.get("outputs", {}).get(output, {}).get("images", [])
        result = next(
            (
                x
                for x in candidates
                if Path(x.get("filename", "")).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
            ),
            None,
        )
        if not result:
            transition(self.factory, job.id, "failed", "Qwen terminó sin una imagen compatible en SaveImage.")
            return
        if not transition(self.factory, job.id, "downloading"):
            return
        tmp = self.settings.tmp_dir / (job.id + "-qwen.part")
        try:
            size = 0
            with client.client.stream(
                "GET", "view", params={k: result[k] for k in ("filename", "subfolder", "type") if k in result}
            ) as response:
                if response.status_code != 200:
                    raise ComfyError("No se pudo recuperar la imagen de Qwen; se reintentará la descarga.")
                with tmp.open("wb") as stream:
                    for chunk in response.iter_bytes():
                        if self.stop_event.is_set():
                            return
                        size += len(chunk)
                        if size > self.settings.max_upload_mb * 1024**2:
                            raise AssetError("La imagen de Qwen supera el límite de almacenamiento.")
                        stream.write(chunk)
            with self.factory() as session, tmp.open("rb") as stream:
                asset = store_image(session, self.settings, stream, "Qwen-" + job.id + ".png")
                session.commit()
                transition(
                    self.factory,
                    job.id,
                    "completed",
                    result_asset_id=asset.id,
                    result_path=asset.rel_path,
                    result_mime=asset.mime,
                    result_sha256=asset.sha256,
                )
        except AssetError as exc:
            transition(self.factory, job.id, "failed", str(exc))
        finally:
            tmp.unlink(missing_ok=True)


def main():
    if get_settings().embedded_worker:
        raise SystemExit("Para un worker separado configura FRUTINOVELAS_EMBEDDED_WORKER=false.")
    from frutinovelas.migrate import upgrade_to_head

    upgrade_to_head()
    worker = GenerationWorker()
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()
