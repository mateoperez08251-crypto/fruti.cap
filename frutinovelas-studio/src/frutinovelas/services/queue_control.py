"""Read and cancel only Studio-owned ComfyUI jobs, never clear the global queue."""
from __future__ import annotations

from sqlalchemy import select

from frutinovelas.db import session_factory
from frutinovelas.models import ChapterRender, GenerationJob
from frutinovelas.services.comfy import ComfyClient, ComfyError, cipher, identity_key
from frutinovelas.services.generation import ACTIVE, transition

TERMINAL = ("completed", "failed", "cancelled")


def queue_ids(snapshot: dict) -> tuple[list[str], list[str]]:
    def ids(key):
        result = []
        for entry in snapshot.get(key, []):
            if isinstance(entry, (list, tuple)) and len(entry) > 1 and isinstance(entry[1], str):
                result.append(entry[1])
        return result
    return ids("queue_running"), ids("queue_pending")


def list_queue(factory=None, client_factory=None):
    factory = factory or session_factory()
    client_factory = client_factory or ComfyClient
    with factory() as session:
        jobs = list(session.scalars(select(GenerationJob).where(GenerationJob.state.in_(ACTIVE))))
        # Use a connection frozen with a job, not an arbitrary default pod.
        groups = {}
        for job in jobs:
            key = (job.snapshot.get("url"), identity_key(job.snapshot.get("identity", {})))
            groups.setdefault(key, []).append(job)
    result = []
    for (url, _), group in groups.items():
        client = client_factory(url, cipher().decrypt(group[0].encrypted_token.encode()).decode())
        try:
            identity = client.get("/frutinovelas/identity")
            if identity_key(identity) != identity_key(group[0].snapshot["identity"]):
                raise ComfyError("Cambió el runtime remoto; no se puede administrar la cola antigua.")
            running, pending = queue_ids(client.get("/queue"))
            for job in group:
                result.append(dict(id=job.id, scene_id=job.scene_id, kind=job.kind, state=job.state,
                                   remote_state=("running" if job.prompt_id in running else
                                                 "pending" if job.prompt_id in pending else "not_found"),
                                   prompt_id=job.prompt_id))
        finally:
            client.close()
    return result


def stop_job(job_id, factory=None, client_factory=None):
    factory = factory or session_factory()
    with factory() as session:
        job = session.get(GenerationJob, job_id)
        if not job:
            raise ComfyError("Generación no encontrada.")
        if job.state == "cancelled":
            return {"id": job.id, "state": "cancelled", "already_stopped": True}
        if job.state not in ACTIVE:
            raise ComfyError("La generación ya terminó; no se puede detener.")
        state = job.state
        prompt_id = job.prompt_id
        url, token, identity = (job.snapshot["url"],
            cipher().decrypt(job.encrypted_token.encode()).decode(), job.snapshot["identity"])
    if state == "queued":
        if not transition(factory, job_id, "cancelled", "Detenida por el usuario antes de enviarse.",
                          expected_states=("queued",)):
            raise ComfyError("La generación cambió de estado; vuelve a consultar.")
        return {"id": job_id, "state": "cancelled", "remote_action": "none"}
    # During upload/submission or unknown receipt, remote delivery is ambiguous;
    # do not release the lock or risk interrupting another generation.
    if state not in ("waiting", "running"):
        raise ComfyError("No es seguro detener esta fase. Espera a que aparezca en la cola o el historial remoto.")
    client = client_factory(url, token)
    try:
        if identity_key(client.get("/frutinovelas/identity")) != identity_key(identity):
            raise ComfyError("Cambió el servidor; no se interrumpirá otro runtime.")
        running, pending = queue_ids(client.get("/queue"))
        if prompt_id in pending:
            client.request("POST", "/queue", json={"delete": [prompt_id]})
            action = "removed_pending"
        elif prompt_id in running:
            if running != [prompt_id]:
                raise ComfyError("Existen otras generaciones ejecutándose; no se usará interrupción global.")
            # ComfyUI /interrupt does not accept prompt_id. Confirm sole running job
            # immediately before requesting interruption to reduce unintended impact.
            second, _ = queue_ids(client.get("/queue"))
            if second != [prompt_id]:
                raise ComfyError("La cola cambió; vuelve a consultar antes de detener.")
            client.request("POST", "/interrupt", json={})
            action = "interrupt_requested"
        else:
            raise ComfyError("El trabajo no figura en la cola. Comprueba el historial antes de cerrarlo.")
    finally:
        client.close()
    # Remote interrupt is asynchronous; preserve local reservation until worker
    # verifies it has disappeared from queue/history.
    if action == "removed_pending":
        if not transition(factory, job_id, "cancelled", "Cancelada en la cola remota.",
                          expected_states=("waiting", "running")):
            raise ComfyError("La cola remota cambió, pero el registro local también cambió. Revisa su estado.")
        return {"id": job_id, "state": "cancelled", "remote_action": action}
    with factory() as session:
        job = session.get(GenerationJob, job_id)
        if job and job.state in ACTIVE:
            job.snapshot = {**job.snapshot, "stop_requested": True}
            session.commit()
    return {"id": job_id, "state": "stopping", "remote_action": action}
