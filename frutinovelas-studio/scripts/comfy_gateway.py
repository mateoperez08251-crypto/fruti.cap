"""Gateway autenticado delante de ComfyUI para FRUTINOVELAS Studio.

ComfyUI escucha solo en 127.0.0.1 dentro del runtime. Este proxy:

- exige un token (``Authorization: Bearer <token>`` o ``X-Frutinovelas-Token``);
- reenvía solo las rutas nativas que usa el programa (lista cerrada), con y sin
  el prefijo ``/api``; no expone gestor de nodos, ficheros de usuario ni otras rutas;
- transmite por streaming subidas y descargas grandes (``/view``) y el WebSocket ``/ws``;
- publica ``/frutinovelas/identity`` y ``/frutinovelas/workflows/<nombre>.api.json``
  para que el programa verifique el servidor y descargue los flujos exportados;
- nunca escribe tokens ni cabeceras en el log.

Uso::

    FRUTI_GATEWAY_TOKEN_FILE=/ruta/token.txt python comfy_gateway.py \
        --listen 127.0.0.1 --port 8189 --upstream http://127.0.0.1:8188 \
        --workflows-dir $DATA_DIR/workflows/api \
        --identity-file $DATA_DIR/identity.json

``--listen 0.0.0.0`` solo cuando un proxy externo (p. ej. el de RunPod) debe alcanzarlo;
el token se exige igualmente en todas las rutas salvo ``/healthz``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

# pyrefly: ignore [missing-import]
from aiohttp import ClientConnectionError, ClientError, ClientSession, ClientTimeout, WSMsgType, web

log = logging.getLogger("frutinovelas.gateway")

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "authorization",
    "x-frutinovelas-token",
    "cookie",
}

GET_ROUTES = [
    r"/system_stats",
    r"/object_info",
    r"/object_info/[^/]+",
    r"/queue",
    r"/history",
    r"/history/[0-9a-fA-F-]{1,64}",
    r"/view",
    r"/prompt",
    r"/features",
    r"/models",
    r"/models/[A-Za-z0-9_\-]+",
    r"/embeddings",
]
POST_ROUTES = [r"/upload/image", r"/prompt", r"/queue", r"/interrupt"]
WORKFLOW_NAME = re.compile(r"^[A-Za-z0-9_.\-]+\.api\.json$")
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
SESSION_KEY = web.AppKey("session", ClientSession)


def _compile(routes: list[str]) -> re.Pattern:
    return re.compile(r"^(?:/api)?(?:" + "|".join(routes) + r")$")


GET_RE = _compile(GET_ROUTES)
POST_RE = _compile(POST_ROUTES)
WS_RE = re.compile(r"^(?:/api)?/ws$")


class FailureLimiter:
    """Limita intentos fallidos de autenticación por IP."""

    def __init__(self, max_failures: int = 20, window_s: float = 60.0):
        self.max_failures = max_failures
        self.window_s = window_s
        self.events: dict[str, deque] = defaultdict(deque)

    def blocked(self, ip: str) -> bool:
        q = self.events[ip]
        now = time.monotonic()
        while q and now - q[0] > self.window_s:
            q.popleft()
        return len(q) >= self.max_failures

    def fail(self, ip: str) -> None:
        self.events[ip].append(time.monotonic())


def extract_token(request: web.Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    tok = request.headers.get("X-Frutinovelas-Token")
    return tok.strip() if tok else None


def create_app(
    upstream: str,
    token: str,
    workflows_dir: Path | None = None,
    identity_file: Path | None = None,
    narration_dir: Path | None = None,
    comfy_output_dir: Path | None = None,
) -> web.Application:
    if not token or len(token) < 16:
        raise ValueError("El token del gateway debe tener al menos 16 caracteres.")
    upstream = upstream.rstrip("/")
    limiter = FailureLimiter()

    @web.middleware
    async def auth_mw(request: web.Request, handler):
        if request.path == "/healthz":
            return await handler(request)
        ip = request.headers.get("CF-Connecting-IP") or request.remote or "?"
        tok = extract_token(request)
        if not tok or not hmac.compare_digest(tok.encode(), token.encode()):
            if limiter.blocked(ip):
                return web.json_response({"error": "demasiados intentos"}, status=429)
            limiter.fail(ip)
            return web.json_response({"error": "no autorizado"}, status=401)
        return await handler(request)

    app = web.Application(middlewares=[auth_mw], client_max_size=MAX_UPLOAD_BYTES)

    async def on_startup(app_: web.Application):
        app_[SESSION_KEY] = ClientSession(
            timeout=ClientTimeout(total=None, connect=15, sock_read=None),
            auto_decompress=False,
        )

    async def on_cleanup(app_: web.Application):
        await app_[SESSION_KEY].close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    async def healthz(_request: web.Request):
        return web.json_response({"ok": True})

    async def identity(_request: web.Request):
        if identity_file and identity_file.is_file():
            data = read_identity()
            if data is None:
                return web.json_response({"error": "identidad no válida; ejecuta fruti start"}, status=503)
            return web.json_response(data)
        return web.json_response({"error": "identidad no disponible"}, status=404)

    def read_identity() -> dict | None:
        if not identity_file:
            return None
        try:
            data = json.loads(identity_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("workflows"), dict):
                return data
        except (OSError, ValueError):
            pass
        return None

    def published_names() -> list[str]:
        if not workflows_dir or not workflows_dir.is_dir():
            return []
        data = read_identity()
        # Una identidad configurada es el inventario validado del arranque actual.
        # Los JSON de perfiles desactivados pueden seguir en disco como respaldo.
        if identity_file and data is None:
            return []
        return sorted(
            p.name
            for p in workflows_dir.iterdir()
            if WORKFLOW_NAME.fullmatch(p.name)
            and p.is_file()
            and p.resolve().parent == workflows_dir.resolve()
            and (data is None or p.name in data["workflows"])
        )

    async def list_workflows(_request: web.Request):
        return web.json_response({"workflows": published_names()})

    async def get_workflow(request: web.Request):
        name = request.match_info["name"]
        if not WORKFLOW_NAME.fullmatch(name) or not workflows_dir:
            return web.json_response({"error": "nombre no válido"}, status=400)
        path = (workflows_dir / name).resolve()
        if path.parent != workflows_dir.resolve() or name not in published_names():
            return web.json_response({"error": "no encontrado"}, status=404)
        body = path.read_bytes()
        data = read_identity()
        if data is not None and hashlib.sha256(body).hexdigest() != data["workflows"].get(name):
            return web.json_response(
                {"error": "workflow modificado; ejecuta fruti start --reexportar"}, status=409
            )
        return web.Response(body=body, content_type="application/json")

    async def proxy_ws(request: web.Request):
        session = request.app[SESSION_KEY]
        target = upstream.replace("http://", "ws://").replace("https://", "wss://") + request.path_qs
        client_ws = web.WebSocketResponse(heartbeat=30, max_msg_size=0)
        await client_ws.prepare(request)
        try:
            async with session.ws_connect(target, heartbeat=30, max_msg_size=0) as up_ws:

                async def up_to_client():
                    async for msg in up_ws:
                        if msg.type == WSMsgType.TEXT:
                            await client_ws.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await client_ws.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break

                async def client_to_up():
                    async for msg in client_ws:
                        if msg.type == WSMsgType.TEXT:
                            await up_ws.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await up_ws.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break

                tasks = [asyncio.create_task(up_to_client()), asyncio.create_task(client_to_up())]
                _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("WS upstream error: %s", type(exc).__name__)
        finally:
            await client_ws.close()
        return client_ws

    async def proxy(request: web.Request):
        path = request.path
        method = request.method.upper()
        if (
            method == "GET"
            and WS_RE.match(path)
            and request.headers.get("Upgrade", "").lower() == "websocket"
        ):
            return await proxy_ws(request)
        if not ((method == "GET" and GET_RE.match(path)) or (method == "POST" and POST_RE.match(path))):
            return web.json_response({"error": "ruta no permitida por el gateway"}, status=403)
        clen = request.content_length
        if clen is not None and clen > MAX_UPLOAD_BYTES:
            return web.json_response({"error": "cuerpo demasiado grande"}, status=413)

        session = request.app[SESSION_KEY]
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        data = request.content if request.can_read_body else None
        started = time.monotonic()
        resp = None
        try:
            async with session.request(
                method, upstream + request.path_qs, headers=headers, data=data, allow_redirects=False
            ) as up:
                resp_headers = {k: v for k, v in up.headers.items() if k.lower() not in HOP_BY_HOP}
                resp = web.StreamResponse(status=up.status, headers=resp_headers)
                await resp.prepare(request)
                async for chunk in up.content.iter_chunked(1 << 20):
                    await resp.write(chunk)
                await resp.write_eof()
        except (ClientError, TimeoutError) as exc:
            log.warning("ComfyUI upstream error: %s", type(exc).__name__)
            if resp is not None and resp.prepared:
                # No convertir una descarga incompleta en un archivo válido con HTTP 200.
                if request.transport:
                    request.transport.close()
                return resp
            status = (
                503
                if isinstance(exc, ClientConnectionError)
                else 504
                if isinstance(exc, TimeoutError)
                else 502
            )
            return web.json_response(
                {
                    "error": "ComfyUI no está disponible; comprueba que esté iniciado.",
                    "code": "comfyui_unavailable",
                    "gateway_available": True,
                },
                status=status,
            )
        log.info("%s %s -> %s (%.2fs)", method, path, up.status, time.monotonic() - started)
        return resp

    if narration_dir is not None:
        from narrated_gateway import NarrationStore, configure_narration
        # Register before the catch-all ComfyUI proxy. Jobs and data stay remote.
        app.on_startup.append(lambda app_: configure_narration(app_, narration_dir, comfy_output_dir))

    app.router.add_get("/healthz", healthz)
    app.router.add_get("/frutinovelas/identity", identity)
    app.router.add_get("/frutinovelas/workflows", list_workflows)
    app.router.add_get("/frutinovelas/workflows/{name}", get_workflow)
    if narration_dir is not None:
        # route registration must occur before application startup and before catch-all
        from narrated_gateway import register_narration_routes
        register_narration_routes(app)
    app.router.add_route("*", "/{tail:.*}", proxy)
    return app


def _read_token() -> str:
    path = os.environ.get("FRUTI_GATEWAY_TOKEN_FILE")
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8").strip()
    tok = os.environ.get("FRUTI_GATEWAY_TOKEN", "").strip()
    if tok:
        return tok
    raise SystemExit("Falta el token: define FRUTI_GATEWAY_TOKEN_FILE o FRUTI_GATEWAY_TOKEN.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gateway autenticado para ComfyUI (FRUTINOVELAS)")
    ap.add_argument("--listen", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8189)
    ap.add_argument("--upstream", default="http://127.0.0.1:8188")
    ap.add_argument("--workflows-dir")
    ap.add_argument("--identity-file")
    ap.add_argument("--narration-dir")
    ap.add_argument("--comfy-output-dir")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    app = create_app(
        args.upstream,
        _read_token(),
        Path(args.workflows_dir) if args.workflows_dir else None,
        Path(args.identity_file) if args.identity_file else None,
        Path(args.narration_dir) if args.narration_dir else None,
        Path(args.comfy_output_dir) if args.comfy_output_dir else None,
    )
    web.run_app(app, host=args.listen, port=args.port, access_log=None, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
