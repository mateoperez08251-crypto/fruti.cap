"""Read ComfyUI's current queue, diagnose stale Studio jobs, and change ONE job at a time.

The current saved connection is the source for live queue inspection. Historical
generation snapshots may point to dead pods: they are reported, not contacted or
allowed to break the entire MCP request. Neither prompts nor tokens are returned.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy import select

from frutinovelas.db import session_factory
from frutinovelas.models import Chapter, ComfyConnection, GenerationJob, Scene
from frutinovelas.services.comfy import ComfyClient, ComfyError, cipher, identity_key
from frutinovelas.services.generation import ACTIVE, transition

TERMINAL = ("completed", "failed", "cancelled")
MAX_QUEUE_ROWS = 500
MAX_HISTORY_CHECKS = 20
GHOST_MIN_AGE_SECONDS = 30


def _valid_prompt_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9-]{1,64}", value))


def _queue_entries(payload, *, strict=False):
    """Normalize ComfyUI 0.40's [priority, id, graph, extra_data, ...] rows.

    Listing tolerates a missing array and reports it as partial. Destructive
    operations reject malformed/partial snapshots instead of interpreting them
    as an empty queue.
    """
    if not isinstance(payload, dict):
        raise ComfyError("El endpoint /queue no devolvió un objeto JSON válido.")
    parsed, warnings = {}, []
    for remote_key, state in (("queue_running", "running"), ("queue_pending", "pending")):
        raw = payload.get(remote_key)
        if not isinstance(raw, list):
            warnings.append(f"missing_or_invalid_{remote_key}")
            raw = []
        if len(raw) > MAX_QUEUE_ROWS:
            warnings.append(f"truncated_{remote_key}")
        parsed[state] = []
        for row in raw[:MAX_QUEUE_ROWS]:
            if not isinstance(row, (list, tuple)) or len(row) < 2 or not _valid_prompt_id(row[1]):
                warnings.append(f"invalid_entry_{remote_key}")
                continue
            graph = row[2] if len(row) > 2 and isinstance(row[2], dict) else {}
            types = {v.get("class_type") for v in graph.values() if isinstance(v, dict)}
            kind = (
                "video" if "SaveVideo" in types or any(
                    isinstance(t, str) and t.startswith("MiniMaxH3") for t in types
                )
                else "image" if "SaveImage" in types else "unknown"
            )
            extra = row[3] if len(row) > 3 and isinstance(row[3], dict) else {}
            client_id = extra.get("client_id")
            parsed[state].append({
                "prompt_id": row[1],
                "state": state,
                "kind": kind,
                "client_id": client_id if isinstance(client_id, str) else None,
            })
    if strict and warnings:
        raise ComfyError("La respuesta de /queue es parcial o incompatible; no se modificó ningún trabajo.")
    return parsed, list(dict.fromkeys(warnings))


def queue_ids(snapshot: dict) -> tuple[list[str], list[str]]:
    """Worker compatibility; fail closed if the queue shape is ambiguous."""
    items, _ = _queue_entries(snapshot, strict=True)
    return [x["prompt_id"] for x in items["running"]], [x["prompt_id"] for x in items["pending"]]


def _error_info(exc: Exception) -> dict:
    """Stable, non-secret diagnostics. Never print request URLs or exception bodies."""
    if isinstance(exc, InvalidToken):
        return {"code": "saved_token_invalid", "message": "No se pudo descifrar el token local guardado."}
    if isinstance(exc, ComfyError):
        status = exc.status_code
        if status in (401, 403):
            return {"code": "gateway_authorization", "http_status": status,
                    "message": f"El gateway rechazó esta operación (HTTP {status})."}
        if status == 404:
            return {"code": "queue_route_missing", "http_status": status,
                    "message": "El gateway no expone la ruta solicitada (HTTP 404)."}
        if status in (301, 302, 303, 307, 308):
            return {"code": "unexpected_redirect", "http_status": status,
                    "message": "El gateway respondió con una redirección no permitida."}
        if status == 429:
            return {"code": "gateway_rate_limited", "http_status": status,
                    "message": "El gateway limita temporalmente las solicitudes."}
        if status and status >= 500:
            return {"code": "gateway_upstream_error", "http_status": status,
                    "message": f"Error del gateway o ComfyUI (HTTP {status})."}
        return {"code": "invalid_queue_response" if status is None else "gateway_http_error",
                "message": "Respuesta de cola inválida o incompatible."}
    if isinstance(exc, httpx.TimeoutException):
        return {"code": "gateway_timeout", "message": "La consulta al gateway agotó el tiempo de espera."}
    if isinstance(exc, httpx.HTTPError):
        return {"code": "gateway_network_error", "message": "No hay conexión de red con el gateway guardado."}
    return {"code": "local_connection_error",
            "message": "No se pudo abrir la conexión guardada; revisa la configuración local."}


def _token(encrypted):
    try:
        return cipher().decrypt(encrypted.encode()).decode()
    except (InvalidToken, ValueError, OSError) as exc:
        raise ComfyError("El token guardado no se pudo descifrar. Revisa la conexión ComfyUI.") from exc


def _current_connection(session):
    return session.get(ComfyConnection, "default")


def _job_rows(session):
    query = (
        select(GenerationJob, Scene.chapter_id, Chapter.project_id)
        .join(Scene, Scene.id == GenerationJob.scene_id)
        .join(Chapter, Chapter.id == Scene.chapter_id)
        .where(GenerationJob.state.in_(ACTIVE))
        .order_by(GenerationJob.created_at)
    )
    result = []
    for job, chapter_id, project_id in session.execute(query):
        snap = job.snapshot or {}
        result.append({
            "id": job.id,
            "scene_id": job.scene_id,
            "chapter_id": chapter_id,
            "project_id": project_id,
            "kind": job.kind,
            "state": job.state,
            "prompt_id": job.prompt_id,
            "url": snap.get("url"),
            "identity": snap.get("identity") or {},
            "stop_requested": bool(snap.get("stop_requested")),
            "created_at": job.created_at,
        })
    return result


def _on_current_runtime(job, connection):
    return bool(
        connection and job["url"] == connection.url
        and identity_key(job["identity"]) == identity_key(connection.identity or {})
    )


def _client(connection, factory):
    return factory(connection.url, _token(connection.encrypted_token))


def _remote_state(row):
    if row["state"] in ("queued", "uploading"):
        return "local_preparing"
    return "unverified"


def _history_state(client, prompt_id):
    if not _valid_prompt_id(prompt_id):
        return "unverified"
    history = client.get("/history/" + prompt_id)
    if not isinstance(history, dict):
        raise ComfyError("El historial remoto no es un objeto JSON válido.")
    record = history.get(prompt_id)
    if prompt_id not in history:
        return "not_found"
    if not isinstance(record, dict):
        return "unknown"
    status = record.get("status")
    if not isinstance(status, dict):
        return "present"
    if status.get("status_str") == "error":
        return "error"
    if status.get("completed") is True:
        return "completed"
    return "present"


def list_queue(factory=None, client_factory=None):
    """Return real remote entries and every active Studio job, including obsolete pods."""
    factory = factory or session_factory()
    client_factory = client_factory or ComfyClient
    with factory() as session:
        connection = _current_connection(session)
        jobs = _job_rows(session)
        # Detached objects retain the credentials needed for the request.
        if connection:
            session.expunge(connection)

    result = {
        "status": "not_configured",
        "server": {"configured": bool(connection), "available": False,
                   "code": "not_configured", "message": "Configura ComfyUI en Studio.",
                   "running_count": None, "pending_count": None,
                   "partial": False, "identity_verified": None},
        "running": [], "pending": [], "local_jobs": [],
        "historical_jobs": 0, "warnings": [],
    }
    for job in jobs:
        historical = bool(connection) and not _on_current_runtime(job, connection)
        if historical:
            result["historical_jobs"] += 1
        result["local_jobs"].append({
            "id": job["id"], "job_id": job["id"],
            "scene_id": job["scene_id"], "chapter_id": job["chapter_id"],
            "project_id": job["project_id"], "kind": job["kind"],
            "state": job["state"], "prompt_id": job["prompt_id"],
            "runtime": "historical" if historical else "current" if connection else "unconfigured",
            "remote_state": "historical_runtime" if historical else _remote_state(job),
            "history_state": "not_checked", "ghost_candidate": False,
            "stop_requested": job["stop_requested"],
        })
    if not connection:
        return result

    client = None
    try:
        client = _client(connection, client_factory)
        # Query /queue on the CURRENT connection even when there are zero local jobs.
        # Checking old snapshot URLs here used to make any obsolete pod break the MCP.
        remote = client.get("/queue")
        entries, warnings = _queue_entries(remote)
        result["warnings"].extend(warnings)
        server = result["server"]
        server.update(available=True, code="ok", message="Cola remota consultada.",
                      running_count=len(entries["running"]), pending_count=len(entries["pending"]),
                      partial=bool(warnings))
        try:
            server["identity_verified"] = (
                identity_key(client.get("/frutinovelas/identity")) ==
                identity_key(connection.identity or {})
            )
            if not server["identity_verified"]:
                result["warnings"].append("remote_runtime_changed")
        except (ComfyError, httpx.HTTPError, ValueError):
            server["identity_verified"] = False
            result["warnings"].append("remote_identity_unavailable")
        by_prompt = {j["prompt_id"]: j for j in jobs if _on_current_runtime(j, connection)}
        locations = {}
        for state in ("running", "pending"):
            for entry in entries[state]:
                prompt_id = entry["prompt_id"]
                locations[prompt_id] = state
                matched = by_prompt.get(prompt_id)
                hint = entry.pop("client_id", None) or ""
                owned_signature = (
                    hint.startswith("frutinovelas-") and
                    _valid_prompt_id(hint[len("frutinovelas-"):])
                )
                entry.update(
                    ownership="studio" if matched else "studio_untracked" if owned_signature else "external",
                    job_id=matched["id"] if matched else None,
                    scene_id=matched["scene_id"] if matched else None,
                    chapter_id=matched["chapter_id"] if matched else None,
                    project_id=matched["project_id"] if matched else None,
                    kind=matched["kind"] if matched else entry["kind"],
                )
                result[state].append(entry)
        checked = 0
        for item in result["local_jobs"]:
            if item["runtime"] != "current":
                continue
            prompt_id = item["prompt_id"]
            if prompt_id in locations:
                item["remote_state"] = locations[prompt_id]
                continue
            if item["state"] in ("queued", "uploading"):
                item["remote_state"] = "local_preparing"
                continue
            if server["partial"] or not server["identity_verified"]:
                item["remote_state"] = "unverified"
                continue
            item["remote_state"] = "not_in_queue"
            if checked >= MAX_HISTORY_CHECKS:
                item["history_state"] = "not_checked_limit"
                continue
            checked += 1
            try:
                item["history_state"] = _history_state(client, prompt_id)
            except (ComfyError, httpx.HTTPError, ValueError) as exc:
                item["history_state"] = "unavailable"
                result["warnings"].append("history_" + _error_info(exc)["code"])
            if (
                item["history_state"] == "not_found"
                and item["state"] in ("waiting", "running", "unknown")
            ):
                item["ghost_candidate"] = True

        result["status"] = "partial" if result["warnings"] else "ok"
    except (ComfyError, httpx.HTTPError, ValueError, OSError) as exc:
        info = _error_info(exc)
        result["status"] = "unreachable"
        result["server"].update(code=info["code"], message=info["message"])
        if "http_status" in info:
            result["server"]["http_status"] = info["http_status"]
        if client is not None:
            try:
                client.get("/system_stats")
                result["server"]["system_stats_reachable"] = True
            except (ComfyError, httpx.HTTPError, ValueError):
                result["server"]["system_stats_reachable"] = False
    finally:
        if client is not None:
            client.close()
    return result


def stop_job(job_id, factory=None, client_factory=None):
    """Stop only the requested job; don't interrupt an unrelated running prompt."""
    factory = factory or session_factory()
    client_factory = client_factory or ComfyClient
    with factory() as session:
        job = session.get(GenerationJob, job_id)
        if not job:
            raise ComfyError("Generación no encontrada.")
        if job.state == "cancelled":
            return {"id": job.id, "state": "cancelled", "already_stopped": True}
        if job.state not in ACTIVE:
            raise ComfyError("La generación ya terminó; no se puede detener.")
        state, prompt_id = job.state, job.prompt_id
        snapshot = job.snapshot or {}
        url, encrypted, identity = snapshot.get("url"), job.encrypted_token, snapshot.get("identity") or {}
        current = _current_connection(session)
        if current and current.url == url and identity_key(current.identity or {}) == identity_key(identity):
            encrypted = current.encrypted_token
    if state in ("queued", "uploading"):
        if not transition(factory, job_id, "cancelled", "Detenida antes de enviarse a ComfyUI.",
                          expected_states=(state,)):
            raise ComfyError("La generación cambió; vuelve a consultar la cola.")
        return {"id": job_id, "state": "cancelled", "remote_action": "none"}
    if state not in ("waiting", "running"):
        raise ComfyError("La recepción o descarga puede seguir activa. Consulta la cola antes de cancelar.")
    if not url:
        raise ComfyError("Falta la conexión congelada de esta generación.")
    client = client_factory(url, _token(encrypted))
    try:
        live_identity = client.get("/frutinovelas/identity")
        if identity_key(live_identity) != identity_key(identity):
            raise ComfyError("La identidad remota cambió; no se interrumpirá otra sesión.")
        first, _ = _queue_entries(client.get("/queue"), strict=True)
        running = [e["prompt_id"] for e in first["running"]]
        pending = [e["prompt_id"] for e in first["pending"]]
        if prompt_id in pending:
            client.request("POST", "/queue", json={"delete": [prompt_id]})
            second, _ = _queue_entries(client.get("/queue"), strict=True)
            if prompt_id in {e["prompt_id"] for group in second.values() for e in group}:
                raise ComfyError("El trabajo aún aparece en ComfyUI. No se ha marcado como cancelado.")
            if _history_state(client, prompt_id) != "not_found":
                return {"id": job_id, "state": state, "remote_action": "recover_history"}
            action = "removed_pending"
        elif prompt_id in running:
            if live_identity.get("comfyui_commit") != "3541246a9c997f4b8c32f9f88f3c985d02021c79":
                raise ComfyError("Este servidor no confirma interrupción por ID. No se enviará una interrupción global.")
            if running != [prompt_id]:
                raise ComfyError("No se puede interrumpir: ComfyUI también ejecuta otros trabajos.")
            again, _ = _queue_entries(client.get("/queue"), strict=True)
            if [e["prompt_id"] for e in again["running"]] != [prompt_id]:
                raise ComfyError("Cambió la ejecución; vuelve a consultar la cola.")
            client.request("POST", "/interrupt", json={"prompt_id": prompt_id})
            action = "interrupt_requested"
        else:
            raise ComfyError("No figura en la cola. Usa la reconciliación de trabajos fantasma.")
    finally:
        client.close()
    if action == "removed_pending":
        if not transition(factory, job_id, "cancelled", "Retirada de la cola remota.",
                          expected_states=("waiting", "running")):
            raise ComfyError("El registro local cambió durante la cancelación. Vuelve a consultar.")
        return {"id": job_id, "state": "cancelled", "remote_action": action}
    with factory() as session:
        job = session.get(GenerationJob, job_id)
        if job and job.state in ACTIVE:
            job.snapshot = {**job.snapshot, "stop_requested": True}
            session.commit()
    return {"id": job_id, "state": "stopping", "remote_action": action}


def _age_seconds(value):
    if value is None:
        return 0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return (datetime.now(UTC) - value).total_seconds()


def reconcile_ghost(job_id, *, detach_old_runtime=False, factory=None, client_factory=None):
    """Manually release a proven missing remote job; old-runtime detach is explicit."""
    from frutinovelas.config import get_settings
    from frutinovelas.worker import WorkerLock

    lock = WorkerLock(get_settings().resolved_data_dir / "generation_worker.lock")
    if not lock.acquire():
        raise ComfyError("El worker está procesando un trabajo; reintenta en unos segundos.")
    try:
        return _reconcile_ghost_locked(job_id, detach_old_runtime=detach_old_runtime,
                                       factory=factory, client_factory=client_factory)
    finally:
        lock.release()


def _reconcile_ghost_locked(job_id, *, detach_old_runtime=False, factory=None, client_factory=None):
    factory = factory or session_factory()
    client_factory = client_factory or ComfyClient
    with factory() as session:
        job = session.get(GenerationJob, job_id)
        current = _current_connection(session)
        if not job:
            raise ComfyError("Generación no encontrada.")
        if job.state == "cancelled":
            return {"id": job.id, "state": "cancelled", "already_resolved": True}
        if job.state not in ACTIVE:
            raise ComfyError("El trabajo ya terminó.")
        if _age_seconds(job.updated_at) < GHOST_MIN_AGE_SECONDS:
            raise ComfyError("Espera al menos 30 segundos antes de reconciliar una generación.")
        state, prompt_id, snap = job.state, job.prompt_id, dict(job.snapshot or {})
        historical = bool(current) and (
            snap.get("url") != current.url or
            identity_key(snap.get("identity") or {}) != identity_key(current.identity or {})
        )
        if historical:
            if not detach_old_runtime:
                raise ComfyError("El trabajo pertenece a un runtime anterior. Para liberar solo el registro "
                                 "local confirma detach_old_runtime=true. No se detendrá el runtime antiguo.")
            allowed = ACTIVE
        else:
            if detach_old_runtime:
                raise ComfyError("No se puede desvincular el runtime actual sin comprobar su cola.")
            if state not in ("unknown", "waiting", "running"):
                raise ComfyError("En esta fase el trabajo aún puede estar enviándose. No se liberó.")
            if not current:
                raise ComfyError("Configura primero el servidor ComfyUI actual.")
            allowed = ("unknown", "waiting", "running")
        if state not in allowed:
            raise ComfyError("Usa Detener generación para los trabajos locales sin enviar.")
    if historical:
        message = ("Desvinculado manualmente del runtime anterior, SIN cancelar la inferencia remota. "
                   "La conexión histórica no se ha verificado.")
        if not transition(factory, job_id, "cancelled", message, expected_states=(state,)):
            raise ComfyError("El trabajo cambió de estado; vuelve a consultar.")
        return {"id": job_id, "state": "cancelled", "remote_action": "not_sent",
                "remote_verified": False, "historical_detached": True}
    client = _client(current, client_factory)
    try:
        if identity_key(client.get("/frutinovelas/identity")) != identity_key(snap.get("identity") or {}):
            raise ComfyError("El runtime cambió; no se puede dar por ausente el trabajo.")
        first, _ = _queue_entries(client.get("/queue"), strict=True)
        history = _history_state(client, prompt_id)
        second, _ = _queue_entries(client.get("/queue"), strict=True)
        all_entries = [e["prompt_id"] for snapshot in (first, second)
                       for group in snapshot.values() for e in group]
        if prompt_id in all_entries:
            raise ComfyError("La generación todavía existe en la cola remota; no es un registro fantasma.")
        if history != "not_found" or _history_state(client, prompt_id) != "not_found":
            raise ComfyError("El resultado está en el historial remoto; Studio debe recuperarlo.")
    finally:
        client.close()
    if not transition(factory, job_id, "cancelled",
                      "Registro fantasma liberado tras dos consultas de cola y una de historial; "
                      "no se envió ningún interrupt a la GPU.",
                      expected_states=(state,)):
        raise ComfyError("El trabajo cambió durante la verificación; vuelve a consultar.")
    return {"id": job_id, "state": "cancelled", "remote_action": "none",
            "remote_verified": True, "history_checked": True}


def remove_untracked_pending(prompt_id, *, factory=None, client_factory=None):
    """Delete exactly one untracked pending ComfyUI prompt, never a running prompt."""
    factory = factory or session_factory()
    client_factory = client_factory or ComfyClient
    try:
        prompt_id = str(UUID(prompt_id))
    except (ValueError, TypeError) as exc:
        raise ComfyError("Indica el UUID real del prompt remoto.") from exc
    with factory() as session:
        connection = _current_connection(session)
        if not connection:
            raise ComfyError("Configura ComfyUI antes de administrar pendientes remotos.")
        current_active = session.scalar(select(GenerationJob.id).where(
            GenerationJob.prompt_id == prompt_id, GenerationJob.state.in_(ACTIVE)))
        if current_active:
            raise ComfyError("Este prompt pertenece a una generación activa de Studio. "
                             "Utiliza Detener generación con su job_id.")
        session.expunge(connection)
    client = _client(connection, client_factory)
    try:
        if identity_key(client.get("/frutinovelas/identity")) != identity_key(connection.identity or {}):
            raise ComfyError("La identidad remota cambió; no se tocará una cola diferente.")
        first, _ = _queue_entries(client.get("/queue"), strict=True)
        if prompt_id in [e["prompt_id"] for e in first["running"]]:
            raise ComfyError("El prompt está ejecutándose. No se pueden interrumpir trabajos externos.")
        if prompt_id not in [e["prompt_id"] for e in first["pending"]]:
            return {"prompt_id": prompt_id, "removed": False, "already_absent": True}
        client.request("POST", "/queue", json={"delete": [prompt_id]})
        second, _ = _queue_entries(client.get("/queue"), strict=True)
        if prompt_id in [e["prompt_id"] for group in second.values() for e in group]:
            raise ComfyError("El prompt sigue apareciendo en ComfyUI; verifica su estado antes de repetir.")
    finally:
        client.close()
    return {"prompt_id": prompt_id, "removed": True, "remote_action": "delete_one_pending"}
