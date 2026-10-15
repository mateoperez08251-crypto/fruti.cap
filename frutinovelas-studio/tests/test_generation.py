from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from conftest import png_bytes
from frutinovelas.api import create_app
from frutinovelas.db import session_factory
from frutinovelas.models import ComfyConnection, GenerationJob
from frutinovelas.services.comfy import ComfyClient
from frutinovelas.worker import GenerationWorker

TOKEN = "private-test-token-not-a-real-secret"
URL = "https://test-gateway.example"
FILENAME = "H3_USUARIO_INICIO_FINAL.api.json"
VIDEO = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00test-video"


def workflow():
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": "initial.png"}},
        "5": {"class_type": "UNETLoader", "inputs": {"unet_name": "preserve-my-model"}},
        "9": {
            "class_type": "MiniMaxH3ImageToVideo",
            "inputs": {
                "width": 576,
                "height": 1024,
                "prompt": "old",
                "first_frame": ["1", 0],
                "last_frame": ["30", 0],
            },
        },
        "12": {"class_type": "RandomNoise", "inputs": {"noise_seed": 42}},
        "14": {"class_type": "BasicScheduler", "inputs": {"steps": 20, "scheduler": "simple"}},
        "20": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "video"}},
        "28": {"class_type": "PrimitiveFloat", "inputs": {"value": 10}},
        "30": {"class_type": "LoadImage", "inputs": {"image": "final.png"}},
    }


class Remote:
    def __init__(self):
        self.raw = json.dumps(workflow()).encode()
        self.identity = {
            "comfyui_commit": "test-version",
            "modelos": {},
            "workflows": {FILENAME: hashlib.sha256(self.raw).hexdigest()},
        }
        self.posts = []
        self.uploads = []
        self.done = False
        self.lose_response = False
        self.post_status = 200

    def handle(self, request):
        assert request.headers.get("authorization") == "Bearer " + TOKEN
        path = request.url.path
        if path == "/system_stats":
            return httpx.Response(200, json={"system": {"comfyui_version": "0.40.0"}})
        if path == "/frutinovelas/identity":
            return httpx.Response(200, json=self.identity)
        if path == "/frutinovelas/workflows/" + FILENAME:
            return httpx.Response(200, content=self.raw)
        if path == "/upload/image":
            self.uploads.append(request.content)
            return httpx.Response(200, json={"name": f"uploaded-{len(self.uploads)}.png", "subfolder": ""})
        if path == "/prompt":
            self.posts.append(json.loads(request.content))
            if self.lose_response:
                raise httpx.ReadTimeout("lost response", request=request)
            if self.post_status != 200:
                return httpx.Response(self.post_status)
            return httpx.Response(200, json={"prompt_id": self.posts[-1]["prompt_id"]})
        if path.startswith("/history/"):
            pid = path.rsplit("/", 1)[-1]
            result = (
                {
                    pid: {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {
                            "20": {"images": [{"filename": "scene.mp4", "subfolder": "", "type": "output"}]}
                        },
                    }
                }
                if self.done and self.posts
                else {}
            )
            return httpx.Response(200, json=result)
        if path == "/queue":
            return httpx.Response(
                200,
                json={
                    "queue_running": [[0, self.posts[-1]["prompt_id"]]]
                    if self.posts and not self.done
                    else [],
                    "queue_pending": [],
                },
            )
        if path == "/view":
            return httpx.Response(200, content=VIDEO)
        return httpx.Response(404)

    def client(self, url, token):
        return ComfyClient(url, token, transport=httpx.MockTransport(self.handle))


@pytest.fixture
def remote(monkeypatch):
    remote = Remote()
    monkeypatch.setattr("frutinovelas.routes.generation.ComfyClient", remote.client)
    return remote


def scene(client, end=True, duration=5):
    project = client.post("/api/v1/projects", json={"name": "Darío"}).json()
    chapter = client.post(f"/api/v1/projects/{project['id']}/chapters", json={"title": "Auto"}).json()
    ids = []
    for color in ((30, 100, 50), (90, 20, 20)):
        ids.append(
            client.post(
                "/api/v1/assets", files={"file": ("frame.png", png_bytes(color), "image/png")}
            ).json()["id"]
        )
    return client.post(
        f"/api/v1/chapters/{chapter['id']}/scenes",
        json={
            "title": "En el auto",
            "start_asset_id": ids[0],
            "end_asset_id": ids[1] if end else None,
            "prompt": "Darío: «Bruno, para ahí». Natural camera cut.",
            "duration_seconds": duration,
        },
    ).json()


def connect(client):
    r = client.put("/api/v1/comfy/connection", json={"url": URL, "token": TOKEN})
    assert r.status_code == 200, r.text
    assert TOKEN not in r.text
    return r.json()


def submit(client, s, id=None):
    return client.post(
        f"/api/v1/scenes/{s['id']}/generate",
        json={"expected_revision": s["revision"], "request_id": id or str(uuid4())},
    )


def test_connection_auth_and_encrypted_persistence(client, remote):
    connect(client)
    with session_factory()() as db:
        c = db.get(ComfyConnection, "default")
        assert c.encrypted_token != TOKEN and TOKEN not in c.encrypted_token
    assert client.get("/api/v1/comfy/connection").json()["configured"]
    assert client.put("/api/v1/comfy/connection", json={"url": URL, "token": ""}).status_code == 200
    # Invalid workflow cannot overwrite the working connection.
    remote.raw = b"{}"
    assert client.put("/api/v1/comfy/connection", json={"url": URL, "token": TOKEN}).status_code == 422
    assert client.get("/api/v1/comfy/connection").json()["configured"]


@pytest.mark.asyncio
async def test_system_status_sends_bearer_token(client, remote):
    connect(client)
    from frutinovelas.routes.system import _comfy_status

    with respx.mock() as mock:
        route = mock.get(URL + "/system_stats", headers={"Authorization": "Bearer " + TOKEN}).respond(
            200, json={"system": {"comfyui_version": "0.40.0"}}
        )
        result = await _comfy_status(URL, TOKEN)
        assert result.reachable and route.called


def test_generate_preserves_revision_downloads_and_keeps_versions(client, remote):
    connect(client)
    s = scene(client)
    job = submit(client, s).json()
    worker = GenerationWorker(client_factory=remote.client)
    try:
        worker.tick()
        assert client.get("/api/v1/generations/" + job["id"]).json()["state"] == "running"
        sent = remote.posts[0]["prompt"]
        assert sent["9"]["inputs"]["prompt"] == s["prompt"]
        assert sent["5"]["inputs"]["unet_name"] == "preserve-my-model"
        assert sent["28"]["inputs"]["value"] == 5
        assert sent["1"]["inputs"]["image"] != sent["30"]["inputs"]["image"]
        remote.done = True
        worker.tick()
        done = client.get("/api/v1/generations/" + job["id"]).json()
        assert done["state"] == "completed" and done["frames"] == 124
        r = client.get(done["result_url"], headers={"Range": "bytes=0-7"})
        assert r.status_code == 206 and r.content == VIDEO[:8]
        # A second version creates another record; no existing video is overwritten.
        second = submit(client, s).json()
        worker.tick()
        assert second["id"] != job["id"]
        assert len(client.get(f"/api/v1/scenes/{s['id']}/generations").json()) == 2
        assert client.get("/api/v1/scenes/" + s["id"]).json()["revision"] == s["revision"]
    finally:
        worker.stop()


def test_timeout_after_acceptance_reconciles_after_restart_without_duplicate(client, remote):
    connect(client)
    s = scene(client, end=False)
    job = submit(client, s).json()
    remote.lose_response = True
    worker = GenerationWorker(client_factory=remote.client)
    worker.tick()
    worker.stop()
    assert client.get("/api/v1/generations/" + job["id"]).json()["state"] == "unknown"
    assert "last_frame" not in remote.posts[0]["prompt"]["9"]["inputs"]
    assert "30" not in remote.posts[0]["prompt"]
    remote.done = True
    worker = GenerationWorker(client_factory=remote.client)
    try:
        worker.tick()
    finally:
        worker.stop()
    assert len(remote.posts) == 1
    assert client.get("/api/v1/generations/" + job["id"]).json()["state"] == "completed"


def test_missing_history_never_resubmits_and_active_request_deduplicates(client, remote):
    connect(client)
    s = scene(client)
    job = submit(client, s).json()
    assert submit(client, s).json()["id"] == job["id"]
    with session_factory()() as db:
        stored = db.get(GenerationJob, job["id"])
        stored.state = "submitting"
        db.commit()
    worker = GenerationWorker(client_factory=remote.client)
    try:
        worker.tick()
        worker.tick()
    finally:
        worker.stop()
    assert remote.posts == []
    assert client.get("/api/v1/generations/" + job["id"]).json()["state"] == "unknown"
    assert client.post("/api/v1/generations/" + job["id"] + "/abandon").status_code == 200
    assert submit(client, s).json()["id"] != job["id"]


def test_validation_before_gpu_and_snapshot_survives_edits(client, remote):
    s = scene(client, duration=3)
    assert submit(client, s).status_code == 422
    connect(client)
    assert submit(client, s).status_code == 422
    r = client.patch(
        "/api/v1/scenes/" + s["id"], json={"expected_revision": s["revision"], "duration_seconds": 5}
    )
    s = r.json()
    job = submit(client, s).json()
    newer = client.patch(
        "/api/v1/scenes/" + s["id"], json={"expected_revision": s["revision"], "prompt": "New prompt"}
    ).json()
    worker = GenerationWorker(client_factory=remote.client)
    try:
        worker.tick()
    finally:
        worker.stop()
    assert remote.posts[0]["prompt"]["9"]["inputs"]["prompt"] == s["prompt"]
    assert newer["prompt"] != s["prompt"]
    assert client.get("/api/v1/generations/" + job["id"]).json()["revision_number"] == s["revision_number"]


def test_worker_lock_prevents_multiple_dispatchers(client, remote):
    connect(client)
    s = scene(client)
    submit(client, s)
    a, b = GenerationWorker(client_factory=remote.client), GenerationWorker(client_factory=remote.client)
    try:
        a.tick()
        b.tick()
    finally:
        a.stop()
        b.stop()
    assert len(remote.posts) == 1


def test_gateway_502_after_acceptance_does_not_resubmit(client, remote):
    connect(client)
    s = scene(client)
    job = submit(client, s).json()
    remote.post_status = 502
    worker = GenerationWorker(client_factory=remote.client)
    try:
        worker.tick()
        assert client.get("/api/v1/generations/" + job["id"]).json()["state"] == "unknown"
        remote.done = True
        worker.tick()
    finally:
        worker.stop()
    assert len(remote.posts) == 1
    assert client.get("/api/v1/generations/" + job["id"]).json()["state"] == "completed"


def test_upgrade_from_phase_one_preserves_data(data_dir):
    from alembic import command

    from frutinovelas.migrate import alembic_config

    command.upgrade(alembic_config(), "0001")
    from frutinovelas.models import Project

    with session_factory()() as db:
        project = Project(name="Existing project")
        db.add(project)
        db.commit()
        id = project.id
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/projects/" + id).json()["name"] == "Existing project"
        assert client.get("/api/v1/comfy/connection").status_code == 200


def test_connection_rejects_url_credentials(client):
    assert (
        client.put(
            "/api/v1/comfy/connection", json={"url": "https://user:password@example.com", "token": TOKEN}
        ).status_code
        == 422
    )
    assert (
        client.put("/api/v1/comfy/connection", json={"url": "http://example.com", "token": TOKEN}).status_code
        == 422
    )
