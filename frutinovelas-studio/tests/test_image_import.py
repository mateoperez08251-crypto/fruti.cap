"""External image import: bytes, guarded HTTPS, idempotency and scene revisions."""
import base64
import io
from uuid import uuid4

import pytest
from PIL import Image

from frutinovelas.services.image_import import (
    ImportErrorImage, download_https, import_image, resolve_public_ips, validate_public_url,
)
from frutinovelas.db import session_factory
from frutinovelas.models import GenerationJob, ImageImportRequest


def png(color="red"):
    output = io.BytesIO()
    Image.new("RGB", (64, 96), color).save(output, "PNG")
    return output.getvalue()


def payload(data=None, **kwargs):
    return {"request_id": str(uuid4()), "filename": "creada.png", "mime_type": "image/png",
            "content_base64": base64.b64encode(data or png()).decode(), **kwargs}


def test_base64_import_reuse_inspect_assign_start_end_and_stale_conflict_no_gpu(client, data_dir):
    body = payload()
    before = client.get("/api/v1/projects").json()
    result = client.post("/api/v1/assets/import", json=body)
    assert result.status_code == 201, result.text
    asset = result.json()
    assert asset["created"] and not asset["reused"]
    assert asset["width"] == 64 and asset["height"] == 96
    assert asset["sha256"] and asset["mime"] == "image/png"
    assert client.get(f"/api/v1/assets/{asset['id']}/thumb").status_code == 200
    again = client.post("/api/v1/assets/import", json=body).json()
    assert again["id"] == asset["id"] and again["reused"]
    identical = client.post("/api/v1/assets/import", json=payload()).json()
    assert identical["id"] == asset["id"] and identical["reused"]
    p = client.post("/api/v1/projects", json={"name": "Case"}).json()
    c = client.post(f"/api/v1/projects/{p['id']}/chapters", json={"title": "Chapter"}).json()
    s = client.post(f"/api/v1/chapters/{c['id']}/scenes", json={"prompt": "Video prompt"}).json()
    start = client.patch(f"/api/v1/scenes/{s['id']}", json={
        "expected_revision": s["revision"], "start_asset_id": asset["id"],
    })
    assert start.status_code == 200
    updated = start.json()
    assert updated["mode"] == "I2VA" and updated["start_asset"]["id"] == asset["id"]
    end = client.patch(f"/api/v1/scenes/{s['id']}", json={
        "expected_revision": updated["revision"], "end_asset_id": asset["id"],
    })
    assert end.status_code == 200 and end.json()["mode"] == "FL2VA"
    stale = client.patch(f"/api/v1/scenes/{s['id']}", json={
        "expected_revision": s["revision"], "end_asset_id": None,
    })
    assert stale.status_code == 409
    assert client.get(f"/api/v1/scenes/{s['id']}").json()["end_asset"]["id"] == asset["id"]
    assert client.get(f"/api/v1/scenes/{s['id']}/revisions").json()
    with session_factory()() as db:
        assert db.query(GenerationJob).count() == 0
        assert db.query(ImageImportRequest).count() == 2


@pytest.mark.parametrize("change", [
    {"content_base64": "not-base64!"}, {"mime_type": "image/jpeg"},
    {"content_base64": base64.b64encode(b"bad image").decode()},
    {"content_base64": ""}, {"filename": "../evil.png"}, 
    {"url": "https://a.example/picture.png"},
])
def test_invalid_payload_rejected(client, change):
    body = payload()
    body.update(change)
    assert client.post("/api/v1/assets/import", json=body).status_code == 422


def test_idempotent_request_rejects_different_content(client):
    body = payload()
    assert client.post("/api/v1/assets/import", json=body).status_code == 201
    body["content_base64"] = base64.b64encode(png("blue")).decode()
    assert client.post("/api/v1/assets/import", json=body).status_code == 422


def test_oversize_and_dimensions(client, monkeypatch):
    from frutinovelas.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "max_image_side", 48)
    assert client.post("/api/v1/assets/import", json=payload()).status_code == 422
    assert client.post("/api/v1/assets/import", json=payload(b"x" * (4*1024*1024 + 1))).status_code == 422


@pytest.mark.parametrize("url", [
    "http://public.example/image.png", "https://127.0.0.1/a", "https://localhost/x",
    "https://192.168.1.1/x", "https://public.example:444/x",
    "https://user:pass@public.example/x", "https://metadata.google.internal/x",
    "https://public.example/a#frag", "https://public.example\n/x",
])
def test_block_url(url):
    with pytest.raises(ImportErrorImage):
        validate_public_url(url)


def test_private_dns_is_rejected(monkeypatch):
    monkeypatch.setattr("frutinovelas.services.image_import.socket.getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))])
    with pytest.raises(ImportErrorImage, match="interna"):
        resolve_public_ips("public.example")


def test_https_import_mock_and_redirect_rejection(client, monkeypatch):
    from frutinovelas.services import image_import
    image = png("green")
    downloads = []
    def fake_downloader(url, limit):
        downloads.append(url)
        return image
    monkeypatch.setattr(image_import, "download_https", fake_downloader)
    body = {"request_id": str(uuid4()), "filename": "external.png",
            "mime_type": "image/png", "url": "https://images.example.org/picture.png"}
    result = client.post("/api/v1/assets/import", json=body)
    assert result.status_code == 201, result.text
    assert downloads == [body["url"]]
    assert client.post("/api/v1/assets/import", json=body).status_code == 201
    assert downloads == [body["url"]]


@pytest.mark.asyncio
async def test_mcp_import_and_inspect_existing_asset(client, monkeypatch):
    from frutinovelas import mcp_studio
    from frutinovelas.mcp_server import create_server
    def proxy(method, path, body=None, raw=False):
        response = client.request(method, "/api/v1/" + path, json=body)
        response.raise_for_status()
        return response.content if raw else response.json()
    monkeypatch.setattr(mcp_studio, "studio_request", proxy)
    server = create_server()
    content = png()
    call = await server.call_tool("import_studio_image", {"request_id": str(uuid4()),
        "filename": "chatgpt.png", "mime_type": "image/png",
        "content_base64": base64.b64encode(content).decode()})
    assert not call.is_error
    asset_id = client.get("/api/v1/projects").json()  # no project or generation was created
    assert asset_id == []
    import json
    result = json.loads(call.content[0].text)
    inspect = await server.call_tool("inspect_studio_image", {"asset_id": result["id"]})
    assert not inspect.is_error
    assert any(part.type == "image" for part in inspect.content)
    with session_factory()() as db:
        assert db.query(GenerationJob).count() == 0



def test_https_stream_response_accepts_small_png_and_rejects_redirect_or_excess(monkeypatch):
    import httpx
    from frutinovelas.services import image_import as imp

    monkeypatch.setattr(imp, "resolve_public_ips", lambda host: ["8.8.8.8"])
    content = png("green")
    responses = [
        httpx.Response(200, content=content, headers={"content-type": "image/png"}),
        httpx.Response(302, headers={"location": "http://127.0.0.1:8765/secrets"}),
        httpx.Response(200, content=b"x" * 250),
    ]
    calls = []

    def handler(req):
        calls.append((str(req.url), req.headers.get("authorization"), req.headers.get("cookie")))
        return responses.pop(0)

    monkeypatch.setattr(imp, "_PinnedHTTPS", lambda host, ip: httpx.MockTransport(handler))
    url = "https://images.example.org/scene.png"
    assert imp.download_https(url, 1000) == content
    with pytest.raises(ImportErrorImage, match="redirecciones"):
        imp.download_https(url, 1000)
    with pytest.raises(ImportErrorImage, match="límite"):
        imp.download_https(url, 100)
    assert len(calls) == 3
    assert all(auth is None and cookie is None for _, auth, cookie in calls)
