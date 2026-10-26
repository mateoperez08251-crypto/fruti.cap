import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from aiohttp.test_utils import TestClient, TestServer
from scripts.build_narration_notebook import OUT, build
from scripts.narrated_server import create_app

from frutinovelas.services import narrated_connection as service
from frutinovelas.services.comfy import ComfyClient, ComfyError


def test_connection_is_encrypted_and_fails_closed(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    connection = service.NarrationConnection(url="https://montage.example/", token="private-token-" * 3, runtime_id=uuid4())
    service.save_connection(connection)
    raw = service.configuration_path().read_bytes()
    assert connection.token.encode() not in raw
    assert service.load_connection() == connection
    service.configuration_path().write_bytes(b"corrupt")
    with pytest.raises(ComfyError):
        service.load_connection()


def test_check_runtime_and_do_not_replace_good_connection_on_failure(data_dir, monkeypatch):
    data_dir.mkdir(parents=True, exist_ok=True)
    runtime_id = str(uuid4())
    response = {"supported": True, "ffmpeg": True, "uploaded_video": True, "runtime_id": runtime_id}
    def handler(request):
        assert request.url.path == "/frutinovelas/narration/capabilities"
        assert request.headers["authorization"] == "Bearer " + "x" * 32
        return httpx.Response(200, json=response)
    monkeypatch.setattr(service, "ComfyClient", lambda url, token: ComfyClient(url, token, transport=httpx.MockTransport(handler)))
    connection = service.check_connection("https://montage.example", "x" * 32)
    saved = service.configuration_path().read_bytes()
    response["runtime_id"] = str(uuid4())
    client = service.ComfyClient(connection.url, connection.token)
    try:
        with pytest.raises(ComfyError, match="cambió de sesión"):
            service.verify_runtime(client, connection)
    finally:
        client.close()
    response["ffmpeg"] = False
    with pytest.raises(ComfyError):
        service.check_connection(connection.url, connection.token)
    assert service.configuration_path().read_bytes() == saved


def test_standalone_server_requires_token_for_all_routes(tmp_path):
    async def verify():
        async with TestClient(TestServer(create_app("x" * 32, tmp_path))) as client:
            assert (await client.get("/frutinovelas/narration/capabilities")).status == 401
            assert (await client.post("/frutinovelas/narration/jobs", json={})).status == 401
            result = await client.get("/frutinovelas/narration/capabilities", headers={"Authorization": "Bearer " + "x" * 32})
            assert result.status == 200
            payload = await result.json()
            assert payload["uploaded_video"]
            assert payload["runtime_id"]
    asyncio.run(verify())


def test_notebook_embeds_current_sources_and_all_cells_compile():
    notebook = build()
    assert json.loads(OUT.read_text(encoding="utf-8")) == notebook
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), cell["id"], "exec")


def test_renderer_api_returns_no_secret_and_is_local_only(client, monkeypatch):
    connection = service.NarrationConnection(url="https://montage.example", token="x" * 32, runtime_id=uuid4())
    monkeypatch.setattr(service, "check_connection", lambda url, token: connection)
    response = client.post("/api/v1/narrated-renderer", json={"url": connection.url, "token": connection.token})
    assert response.status_code == 200
    assert "token" not in response.json()
    assert client.post("/api/v1/narrated-renderer", headers={"origin": "https://other.example"}, json={"url": connection.url, "token": connection.token}).status_code == 403
