"""Gateway HTTP real en loopback; upstream simulado, sin acceso GPU."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, unused_port

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from comfy_gateway import create_app  # noqa: E402

TOKEN = "test-token-at-least-16"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


async def test_gateway_reports_comfy_offline_separately():
    async with TestClient(TestServer(create_app(f"http://127.0.0.1:{unused_port()}", TOKEN))) as client:
        assert (await client.get("/healthz")).status == 200
        assert (await client.get("/system_stats")).status == 401
        response = await client.get("/system_stats", headers=AUTH)
        assert response.status == 503
        payload = await response.json()
        assert payload["code"] == "comfyui_unavailable"
        assert payload["gateway_available"] is True
        assert TOKEN not in json.dumps(payload)


async def test_gateway_only_serves_workflows_in_current_identity(tmp_path):
    body = b'{"1":{"class_type":"SaveImage","inputs":{}}}'
    (tmp_path / "active.api.json").write_bytes(body)
    (tmp_path / "disabled_qwen.api.json").write_bytes(body)
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"workflows": {"active.api.json": hashlib.sha256(body).hexdigest()}}))
    app = create_app("http://127.0.0.1:1", TOKEN, tmp_path, identity)
    async with TestClient(TestServer(app)) as client:
        listing = await (await client.get("/frutinovelas/workflows", headers=AUTH)).json()
        assert listing == {"workflows": ["active.api.json"]}
        assert (
            await client.get("/frutinovelas/workflows/disabled_qwen.api.json", headers=AUTH)
        ).status == 404
        assert (await client.get("/frutinovelas/workflows/active.api.json", headers=AUTH)).status == 200
        (tmp_path / "active.api.json").write_bytes(body + b" ")
        assert (await client.get("/frutinovelas/workflows/active.api.json", headers=AUTH)).status == 409
        identity.write_text("invalid")
        assert (await client.get("/frutinovelas/identity", headers=AUTH)).status == 503
        assert await (await client.get("/frutinovelas/workflows", headers=AUTH)).json() == {"workflows": []}


async def test_failed_auth_does_not_block_valid_token_and_proxy_strips_secrets():
    observed = {}

    async def stats(request):
        observed.update(dict(request.headers))
        return web.json_response({"system": {"comfyui_version": "test"}})

    upstream = web.Application()
    upstream.router.add_get("/system_stats", stats)
    async with TestServer(upstream) as server:
        async with TestClient(TestServer(create_app(str(server.make_url("")).rstrip("/"), TOKEN))) as client:
            for _ in range(20):
                assert (await client.get("/system_stats")).status == 401
            assert (await client.get("/system_stats")).status == 429
            response = await client.get("/system_stats", headers={**AUTH, "Cookie": "private=true"})
            assert response.status == 200
            assert "Authorization" not in observed
            assert "Cookie" not in observed
