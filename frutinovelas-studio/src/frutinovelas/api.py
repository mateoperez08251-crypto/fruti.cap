"""Servidor web de FRUTINOVELAS Studio: API v1 + interfaz compilada.

Uso::

    frutinovelas-api                 # arranca y abre el navegador
    python -m frutinovelas.api --no-browser
    python -m frutinovelas.api --host 127.0.0.1 --port 8765

En desarrollo, Vite (``npm run dev`` en ``frontend/``) usa proxy hacia ``/api``.
En uso normal, este servidor entrega la interfaz ya compilada desde ``frontend/dist``.
"""

from __future__ import annotations

import argparse
import logging
import secrets
import socket
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from frutinovelas import __version__
from frutinovelas.config import APP_NAME, get_settings
from frutinovelas.migrate import upgrade_to_head
from frutinovelas.routes import (
    assets,
    characters,
    generation,
    images,
    mcp_connection,
    narrated,
    projects,
    prompts,
    renders,
    scenes,
    system,
)
from frutinovelas.worker import GenerationWorker

log = logging.getLogger("frutinovelas.api")

API_PREFIX = "/api/v1"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def frontend_dir() -> Path | None:
    here = Path(__file__).resolve().parent
    for candidate in (here / "_frontend", here.parents[1] / "frontend" / "dist"):
        if (candidate / "index.html").is_file():
            return candidate
    return None


class SPAStaticFiles(StaticFiles):
    """Sirve la interfaz y devuelve index.html para las rutas del lado cliente."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api/"):
                return await super().get_response("index.html", scope)
            raise


_MISSING_UI = """<!doctype html><html lang="es"><meta charset="utf-8">
<title>FRUTINOVELAS Studio</title>
<body style="font-family:system-ui;background:#0f0d16;color:#eee;padding:3rem;line-height:1.6">
<h1>La interfaz no está compilada</h1>
<p>El servidor funciona (<a style="color:#f9b44a" href="/docs">API</a>), pero falta compilar la interfaz:</p>
<pre style="background:#1c1828;padding:1rem;border-radius:8px">cd frontend
npm ci
npm run build</pre>
<p>Después vuelve a abrir esta página.</p></body></html>"""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    upgrade_to_head()
    log.info("Datos en %s", settings.resolved_data_dir)
    worker = GenerationWorker()
    if settings.embedded_worker:
        worker.start()
    try:
        yield
    finally:
        worker.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=APP_NAME,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(StaleDataError)
    async def concurrent_edit(_request: Request, _exc: StaleDataError):
        return JSONResponse(
            {"detail": "El registro cambió mientras lo editabas. Recarga y vuelve a intentarlo."},
            status_code=409,
        )

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        token = settings.api_token
        if token and request.url.path.startswith("/api/") and request.method not in SAFE_METHODS:
            sent = request.headers.get("authorization", "")
            if not secrets.compare_digest(sent, f"Bearer {token}"):
                return JSONResponse({"detail": "Se requiere autorización."}, status_code=401)
        return await call_next(request)

    for module in (system, projects, scenes, assets, generation, prompts, characters, images, renders, mcp_connection, narrated):
        app.include_router(module.router, prefix=API_PREFIX)

    ui = frontend_dir()
    if ui is not None:
        app.mount("/", SPAStaticFiles(directory=ui, html=True), name="ui")
    else:

        @app.get("/", include_in_schema=False)
        def missing_ui():
            return HTMLResponse(_MISSING_UI)

    return app


# --------------------------------------------------------------------------- arranque


def _port_in_use(host: str, port: int) -> bool:
    probe = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    try:
        with socket.create_connection((probe, port), timeout=1):
            return True
    except OSError:
        return False


def _already_running(url: str) -> bool:
    try:
        r = httpx.get(f"{url}{API_PREFIX}/health", timeout=2)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    settings = get_settings()
    parser = argparse.ArgumentParser(prog="frutinovelas-api", description=f"Arranca {APP_NAME}.")
    parser.add_argument("--host", default=settings.api_host, help=f"interfaz de red ({settings.api_host})")
    parser.add_argument("--port", type=int, default=settings.api_port, help=f"puerto ({settings.api_port})")
    parser.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    args = parser.parse_args(argv)

    # El asistente MCP y los servicios deben anunciar el puerto real de esta instancia.
    settings.api_host = args.host
    settings.api_port = args.port

    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")
    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{shown_host}:{args.port}"

    if args.host not in LOOPBACK and not settings.api_token:
        print(
            f"Rechazado: escuchar en {args.host} expone el programa en la red sin protección.\n"
            "Define FRUTINOVELAS_API_TOKEN o usa --host 127.0.0.1.",
            file=sys.stderr,
        )
        return 2

    if _port_in_use(args.host, args.port):
        if _already_running(url):
            print(f"{APP_NAME} ya está en marcha en {url}")
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        print(
            f"El puerto {args.port} está ocupado por otro programa. Usa --port con otro número.",
            file=sys.stderr,
        )
        return 1

    if frontend_dir() is None:
        print(
            "Aviso: la interfaz no está compilada (cd frontend && npm ci && npm run build).", file=sys.stderr
        )

    print(f"{APP_NAME} {__version__} — abre {url}  (Ctrl+C para detener)")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
