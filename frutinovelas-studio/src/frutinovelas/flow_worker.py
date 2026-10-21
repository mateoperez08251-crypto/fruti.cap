"""A single desktop lane. Never repeat an ambiguous submission."""
import logging
import threading

import httpx
from sqlalchemy import select

from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.models import FlowConnection, FlowJob
from frutinovelas.services import flow
from frutinovelas.services.flow_media import digest_file
from frutinovelas.services.flow_transport import FlowClient, FlowError, FlowRejected, flow_dir

log = logging.getLogger(__name__)


class FlowWorker:
    def __init__(self, factory=None, client_factory=FlowClient):
        self.factory = factory or session_factory()
        self.client_factory = client_factory
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name="flow-worker")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except FlowError:
                pass  # Another process owns the lane; no speculative state changes.
            except Exception:
                log.error("La cola Flow requiere revisión; no se reenviaron solicitudes.")
            self.stop_event.wait(get_settings().flow_poll_seconds)

    def tick(self):
        with flow.operation_lock():
            self._tick()

    def _tick(self):
        with self.factory() as s:
            connection = s.get(FlowConnection, "default")
            if not connection or not connection.connected:
                return
            approved = s.scalar(select(FlowJob).where(FlowJob.kind == "image", FlowJob.state == "completed",
                                FlowJob.approval == "pending", FlowJob.error == "",
                                FlowJob.snapshot["automatic_approval"].as_boolean().is_(True))
                                .order_by(FlowJob.created_at).limit(1))
            if approved and not approved.error:
                try:
                    flow.review(s, approved, approved.snapshot["scene_revision"], "approved")
                except (ValueError, RuntimeError) as exc:
                    s.rollback()
                    approved = s.get(FlowJob, approved.id)
                    approved.error = str(exc)
                    s.commit()
            # Any uncertain remote work blocks all subsequent submissions on this desktop.
            job = s.scalar(select(FlowJob).where(FlowJob.state.in_((*flow.REMOTE, "awaiting_import")))
                           .order_by(FlowJob.created_at, FlowJob.position).limit(1))
            if job is None:
                job = s.scalar(select(FlowJob).where(FlowJob.state == "queued")
                               .order_by(FlowJob.kind, FlowJob.created_at, FlowJob.position).limit(1))
            if job is None or job.state == "awaiting_import":
                return
            job_id = job.id
            if job.state == "queued" and job.snapshot["mode"] == "assisted":
                flow.change(s, job, "awaiting_import", "Copia el prompt guardado, genera en Flow e importa la descarga de esta escena.")
                s.commit()
                return
            if connection.agent_id != job.snapshot["agent_id"]:
                job.error = "La identidad del agente cambió. Reconcilia este trabajo antes de conectar otro agente."
                s.commit()
                return
            submit = job.state == "queued"
            payload = None
            if submit:
                try:
                    payload = flow.agent_payload(s, job)
                except FlowError as exc:
                    flow.change(s, job, "failed", str(exc), remote_stopped=True)
                    s.commit()
                    return
                # Commit before any external action. Crash here => unknown, never automatic resubmit.
                flow.change(s, job, "submitting")
                s.commit()
            else:
                s.rollback()
            snapshot_agent = job.snapshot["agent_id"]
        client = self.client_factory()
        try:
            status = client.request("GET", "status")
            if not status or status.get("agent_id") != snapshot_agent:
                raise FlowError("La identidad del agente no coincide con la solicitud original.")
            result = client.request("POST", "jobs", payload) if submit else client.request("GET", f"jobs/{job_id}")
            if result is None:
                raise FlowError("El agente no reconoce el envío. No se reenviará automáticamente.")
            if result.get("id") != job_id or result.get("agent_id") != snapshot_agent:
                raise FlowError("La respuesta no corresponde a este trabajo.")
            with self.factory() as s:
                job = s.get(FlowJob, job_id)
                if job.cancel_requested:
                    result = client.request("POST", f"jobs/{job_id}/cancel", {}) or result
                state = result.get("state")
                if state == "completed":
                    flow.change(s, job, "downloading")
                    s.commit()
                    path = flow_dir() / (job_id + ".part")
                    try:
                        limit = (get_settings().flow_max_video_mb if job.kind == "video" else get_settings().max_upload_mb) * 1024**2
                        client.download(job_id, path, limit)
                        if digest_file(path) != result.get("sha256"):
                            raise FlowError("La descarga no coincide con el resultado del agente.")
                        flow.import_result(s, job, path)
                    finally:
                        path.unlink(missing_ok=True)
                elif state in ("failed", "cancelled") and result.get("remote_stopped") is True:
                    flow.change(s, job, state, result.get("error", ""), remote_stopped=True)
                    s.commit()
                elif state in ("queued", "preparing", "running", "submitting"):
                    flow.change(s, job, "cancel_requested" if job.cancel_requested else "running",
                                "Cancelación local solicitada; generación remota sin detener." if job.cancel_requested else "")
                    s.commit()
                else:
                    flow.change(s, job, "blocked" if state == "blocked" else "unknown",
                                result.get("error") or "Estado remoto incierto. Se conserva la reserva.")
                    s.commit()
        except FlowRejected as exc:
            with self.factory() as s:
                job = s.get(FlowJob, job_id)
                flow.change(s, job, "failed", str(exc), remote_stopped=True)
                s.commit()
        except (httpx.HTTPError, FlowError, ValueError, OSError) as exc:
            with self.factory() as s:
                job = s.get(FlowJob, job_id)
                if job and job.state not in flow.TERMINAL:
                    message = str(exc) if isinstance(exc, FlowError) else "Agente desconectado o resultado ilegible. Se recuperará por ID sin reenviar."
                    flow.change(s, job, "unknown", message)
                    s.commit()
        finally:
            client.close()
