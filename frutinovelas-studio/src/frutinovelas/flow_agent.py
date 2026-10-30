"""Authenticated loopback Windows agent with its own durable submission journal."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from frutinovelas.config import get_settings
from frutinovelas.flow_uia import Profile, UIADriver, inspect_application, uia_thread
from frutinovelas.services.assets import _probe_image
from frutinovelas.services.flow_media import digest_file, probe_video
from frutinovelas.services.flow_transport import FlowError, FlowIntervention, flow_dir, local_secret
from frutinovelas.worker import WorkerLock


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_base64: str = Field(max_length=14 * 1024**2)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_agent_id: UUID
    kind: Literal["image", "video"]
    prompt: str = Field(min_length=1, max_length=24000)
    aspect_ratio: Literal["9:16", "16:9", "1:1"]
    duration_seconds: float | None = Field(default=None, gt=0, le=60)
    references: list[Reference] = Field(default_factory=list, max_length=3)


class Journal:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "agent.sqlite3"
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('identity', ?)", (str(uuid4()),))
            self.identity = db.execute("SELECT value FROM settings WHERE key='identity'").fetchone()[0]
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
                slot INTEGER UNIQUE, error TEXT NOT NULL DEFAULT '', remote_stopped INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0, sha256 TEXT, mime TEXT,
                created REAL NOT NULL, updated REAL NOT NULL)""")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.db() as db:
            db.execute("UPDATE jobs SET state='unknown',error='El agente se reinició durante una operación. Verifica Flow; no se reenviará.',updated=? WHERE state IN ('preparing','submitting','running','saving')", (time.time(),))

    def public(self, row):
        if row is None:
            return None
        return {"id": row["id"], "agent_id": self.identity, "state": row["state"], "error": row["error"],
                "remote_stopped": bool(row["remote_stopped"]), "cancel_requested": bool(row["cancel_requested"]),
                "sha256": row["sha256"], "mime": row["mime"]}

    def get(self, job_id):
        with self.db() as db:
            return db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def submit(self, payload):
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM jobs WHERE id=?", (payload["request_id"],)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise FlowError("El ID pertenece a otro contenido. No se envió nada.")
                return self.public(old)
            if db.execute("SELECT 1 FROM jobs WHERE slot=1").fetchone():
                raise FlowError("Hay otro trabajo activo o incierto en este escritorio.")
            db.execute("INSERT INTO jobs (id,fingerprint,payload,state,slot,created,updated) VALUES (?,?,?,'queued',1,?,?)",
                       (payload["request_id"], fingerprint, text, time.time(), time.time()))
        return self.public(self.get(payload["request_id"]))

    def set(self, job_id, state, error="", remote_stopped=False, sha256=None, mime=None):
        slot = None if state in ("completed", "failed", "cancelled") and remote_stopped else 1
        with self.db() as db:
            db.execute("UPDATE jobs SET state=?,error=?,remote_stopped=?,slot=?,updated=?,sha256=COALESCE(?,sha256),mime=COALESCE(?,mime) WHERE id=?",
                       (state, error, remote_stopped, slot, time.time(), sha256, mime, job_id))

    def cancel(self, job_id):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return None
            if row["state"] == "queued":
                db.execute("UPDATE jobs SET state='cancelled',remote_stopped=1,slot=NULL,cancel_requested=1,updated=? WHERE id=?", (time.time(), job_id))
            elif row["state"] not in ("completed", "failed", "cancelled"):
                db.execute("UPDATE jobs SET cancel_requested=1,error='Cancelación local solicitada; no existe detención remota verificada.',updated=? WHERE id=?", (time.time(), job_id))
        return self.public(self.get(job_id))

    def claim(self):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET state='preparing',updated=? WHERE id=? AND state='queued'", (time.time(), row["id"]))
            return row

    def result_path(self, job_id):
        row = self.get(job_id)
        if row is None:
            raise FlowError("Trabajo no encontrado.")
        kind = json.loads(row["payload"])["kind"]
        return self.folder / "outputs" / (job_id + (".mp4" if kind == "video" else ".png"))


class AgentRunner:
    def __init__(self, journal, driver):
        self.journal, self.driver = journal, driver
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            row = self.journal.claim()
            if row:
                self.execute(row)
            self.stop.wait(2)

    @uia_thread
    def execute(self, row):
        job_id = row["id"]
        payload = json.loads(row["payload"])
        sent = False
        try:
            if self.driver is None:
                raise FlowError("No hay perfil UIA verificado.")
            mode = self.driver.validate_request(payload)
            self.driver.bind()
            self.driver.verify()
            # A pre-existing result/busy marker makes correlation unsafe.
            if self.driver.find(mode.busy, optional=True) or self.driver.find(mode.completed, optional=True):
                raise FlowError("Hay una generación o resultado previo visible. Abre una vista limpia para correlacionar esta solicitud.")
            output = self.journal.result_path(job_id)
            output.parent.mkdir(exist_ok=True)
            if output.exists():
                raise FlowError("Ya existe un archivo para este trabajo; se conserva sin reenviar.")
            values = {**payload, "output_path": str(output)}
            inputs = self.journal.folder / "inputs" / job_id
            inputs.mkdir(parents=True, exist_ok=True)
            for index, ref in enumerate(payload["references"]):
                raw = base64.b64decode(ref["content_base64"], validate=True)
                if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                    raise FlowError("Referencia dañada en tránsito.")
                path = inputs / f"reference-{index}.part"
                path.write_bytes(raw)
                probe = _probe_image(path, get_settings().max_image_side)
                target = path.with_suffix({"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[probe.fmt])
                path.rename(target)
                path = target
                values[f"reference_{index}"] = str(path)
            self.driver.actions(mode.prepare, values)
            self.driver.verify()
            if self.driver.find(mode.busy, optional=True) or self.driver.find(mode.completed, optional=True):
                raise FlowError("La ventana cambió durante la preparación. No se envió otra generación.")
            submit = self.driver.find(mode.submit)
            if not submit.is_enabled():
                raise FlowError("La generación está deshabilitada.")
            if self.journal.get(job_id)["cancel_requested"]:
                self.journal.set(job_id, "cancelled", remote_stopped=True)
                return
            # Once committed, every exception/crash is uncertain, including invoke failure.
            self.journal.set(job_id, "submitting")
            sent = True
            submit.invoke()
            self.journal.set(job_id, "running")
            deadline = time.monotonic() + self.driver.profile.timeout_seconds
            while not self.stop.is_set() and time.monotonic() < deadline:
                self.driver.check_blockers()
                if self.driver.find(mode.completed, optional=True) is not None:
                    self.journal.set(job_id, "saving")
                    self.driver.actions(mode.save, values)
                    break
                self.stop.wait(3)
            else:
                raise FlowError("No se pudo confirmar el resultado dentro del plazo. Verifica Flow sin reenviar.")
            previous = None
            while not self.stop.is_set() and time.monotonic() < deadline:
                if output.is_file():
                    current = (output.stat().st_size, output.stat().st_mtime_ns)
                    limit = (get_settings().flow_max_video_mb if payload["kind"] == "video" else get_settings().max_upload_mb) * 1024**2
                    if current[0] > limit:
                        raise FlowError("La descarga supera el límite de almacenamiento.")
                    if current == previous and current[0] > 0:
                        if payload["kind"] == "image":
                            p = _probe_image(output, get_settings().max_image_side)
                            mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[p.fmt]
                        else:
                            probe_video(output)
                            mime = "video/mp4"
                        self.journal.set(job_id, "completed", remote_stopped=True, sha256=digest_file(output), mime=mime)
                        return
                    previous = current
                self.stop.wait(3)
            raise FlowError("La descarga no terminó. El resultado no se marcará como completado.")
        except Exception as exc:
            message = str(exc) if isinstance(exc, FlowError) else "Falló un control o la validación del archivo; revisa el agente local."
            state = "blocked" if isinstance(exc, FlowIntervention) else "unknown" if sent else "failed"
            self.journal.set(job_id, state, message, remote_stopped=not sent)


def create_agent_app(journal=None, driver=None, *, start_runner=True):
    journal = journal or Journal(flow_dir() / "agent")
    token = local_secret("agent")
    lock = WorkerLock(journal.folder / "process.lock")
    runner = AgentRunner(journal, driver)

    @asynccontextmanager
    async def lifespan(_app):
        if not lock.acquire():
            raise RuntimeError("El agente ya está abierto.")
        journal.recover()
        thread = None
        if start_runner:
            thread = threading.Thread(target=runner.run, daemon=True)
            thread.start()
        try:
            yield
        finally:
            runner.stop.set()
            if thread:
                thread.join(timeout=5)
            if not thread or not thread.is_alive():
                lock.release()

    app = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None, redoc_url=None)

    @app.middleware("http")
    async def authorize(request: Request, call_next):
        if (request.url.hostname not in ("127.0.0.1", "localhost", "::1", "testserver")
                or request.headers.get("origin") or request.headers.get("forwarded")
                or request.headers.get("x-forwarded-for")):
            return JSONResponse({"detail": "Solo comunicación local autenticada."}, status_code=403)
        if not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            return JSONResponse({"detail": "Autenticación requerida."}, status_code=401)
        if int(request.headers.get("content-length", "0")) > 45 * 1024**2:
            return JSONResponse({"detail": "Solicitud demasiado grande."}, status_code=413)
        return await call_next(request)

    @app.get("/status")
    def status():
        result = driver.status() if driver else {"available": False, "window_open": None, "flow_available": None,
                                               "authentication": "unknown", "modes": {}, "detail": "El agente está abierto, pero falta configurar el perfil de Userflex. Consulta la guía de instalación de Flow Automation."}
        return {**result, "agent_id": journal.identity, "profile_configured": driver is not None}

    @app.post("/focus")
    def focus():
        if driver is None:
            raise HTTPException(409, "Configura el perfil local.")
        try:
            driver.focus()
            return {"focused": True}
        except Exception as exc:
            raise HTTPException(409, "Ventana autorizada no disponible.") from exc

    @app.post("/jobs")
    def submit(body: Submission):
        if str(body.expected_agent_id) != journal.identity:
            raise HTTPException(409, "El agente no coincide con la solicitud.")
        payload = body.model_dump(mode="json")
        try:
            # Validate capability before journal acceptance; still no generation here.
            if driver is None:
                raise FlowError("Falta el perfil verificado.")
            driver.validate_request(payload)
        except FlowError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            return journal.submit(payload)
        except FlowError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/jobs/{job_id}")
    def job(job_id: UUID):
        result = journal.public(journal.get(str(job_id)))
        if result is None:
            raise HTTPException(404, "Trabajo no encontrado.")
        return result

    @app.post("/jobs/{job_id}/cancel")
    def cancel(job_id: UUID):
        result = journal.cancel(str(job_id))
        if result is None:
            raise HTTPException(404, "Trabajo no encontrado.")
        return result

    @app.get("/jobs/{job_id}/content")
    def content(job_id: UUID):
        row = journal.get(str(job_id))
        if row is None or row["state"] != "completed":
            raise HTTPException(409, "El resultado aún no está verificado.")
        path = journal.result_path(str(job_id))
        if not path.is_file() or digest_file(path) != row["sha256"]:
            raise HTTPException(409, "El resultado falta o cambió.")
        return FileResponse(path, media_type=row["mime"])

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agente Flow local; nunca expone el escritorio en Internet.")
    parser.add_argument("command", choices=["serve", "inspect", "schema", "verify-profile", "resolve", "vision-connect"])
    parser.add_argument("--profile", type=Path, default=flow_dir() / "profile.json")
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--output", type=Path, help="Guardar inspect/schema directamente como JSON UTF-8.")
    parser.add_argument("--include-edit-labels", action="store_true",
                        help="Incluir nombres accesibles de campos no secretos; vacía los campos antes de inspeccionar.")
    parser.add_argument("--job-id", type=UUID)
    parser.add_argument("--confirmed-no-remote-work", action="store_true")
    args = parser.parse_args(argv)
    if args.output and args.command not in ("inspect", "schema"):
        parser.error("--output solo se utiliza con inspect o schema.")
    if args.include_edit_labels and args.command != "inspect":
        parser.error("--include-edit-labels solo se utiliza con inspect.")
    try:
        if args.command == "vision-connect":
            from frutinovelas.flow_vision import connect_interactively
            connect_interactively()
        elif args.command in ("schema", "inspect"):
            if args.command == "schema":
                document = Profile.model_json_schema()
            else:
                if not args.executable:
                    parser.error("inspect requiere --executable con la ruta exacta del programa autorizado.")
                document = inspect_application(args.executable, include_edit_labels=args.include_edit_labels)
            # Escaped JSON survives legacy PowerShell console code pages. Direct files use UTF-8.
            serialized = json.dumps(document, ensure_ascii=args.output is None, indent=2) + "\n"
            if args.output:
                args.output.write_text(serialized, encoding="utf-8")
                print("Diagnostico guardado en el archivo indicado.")
            else:
                print(serialized, end="")
        elif args.command == "resolve":
            if not args.job_id or not args.confirmed_no_remote_work:
                parser.error("Comprueba el trabajo en Flow y usa --job-id y --confirmed-no-remote-work.")
            journal = Journal(flow_dir() / "agent")
            lock = WorkerLock(journal.folder / "process.lock")
            if not lock.acquire():
                raise FlowError("Cierra el agente antes de reconciliar su diario.")
            try:
                row = journal.get(str(args.job_id))
                if row is None or row["state"] in ("completed", "failed"):
                    raise FlowError("No hay un trabajo incierto con ese ID.")
                journal.set(str(args.job_id), "cancelled", "Cierre confirmado manualmente en Windows.", remote_stopped=True)
            finally:
                lock.release()
            print("Reserva liberada. Reinicia el agente para reconciliar Studio.")
        elif args.command == "verify-profile":
            UIADriver(args.profile).mark_verified()
            print("Controles principales verificados. Falta la prueba completa de generación y descarga.")
        else:
            import uvicorn
            driver = UIADriver(args.profile) if args.profile.is_file() else None
            uvicorn.run(create_agent_app(driver=driver), host="127.0.0.1", port=get_settings().flow_agent_port,
                        access_log=False, proxy_headers=False)
        return 0
    except (FlowError, OSError, ValueError) as exc:
        print(f"No se pudo iniciar la operación: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
