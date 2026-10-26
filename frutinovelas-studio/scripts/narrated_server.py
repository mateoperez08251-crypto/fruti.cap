"""Standalone narration assembly gateway, without ComfyUI or GPU inference."""
from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from aiohttp import web

try:
    from .narrated_gateway import register_narration_routes
except ImportError:
    from narrated_gateway import register_narration_routes


def create_app(token: str, root: Path) -> web.Application:
    if len(token) < 24:
        raise ValueError("Usa un token de al menos 24 caracteres.")

    @web.middleware
    async def authorize(request, handler):
        if not secrets.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
            raise web.HTTPUnauthorized(text="Autenticación requerida.")
        return await handler(request)

    app = web.Application(middlewares=[authorize], client_max_size=70 * 1024**2)
    register_narration_routes(app, root)
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="Montaje remoto de imágenes, clips y audio; no requiere GPU.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8199)
    args = parser.parse_args(argv)
    token = os.environ.get("FRUTINOVELAS_NARRATION_TOKEN", "")
    web.run_app(create_app(token, args.root), host="127.0.0.1", port=args.port, access_log=None)


if __name__ == "__main__":
    main()
