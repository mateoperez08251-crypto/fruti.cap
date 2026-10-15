"""Character identity binding and Qwen queue integration, using a simulated GPU gateway."""

import copy
import hashlib
import json
from uuid import uuid4

import httpx
import pytest

from conftest import png_bytes
from frutinovelas.db import session_factory
from frutinovelas.models import GenerationJob
from frutinovelas.services.comfy import ComfyError
from frutinovelas.services.image_generation import EDIT_WORKFLOW, T2I_WORKFLOW, prepare_image_graph
from frutinovelas.worker import GenerationWorker
from test_generation import TOKEN, Remote, connect, scene


def graph(edit=True):
    kind = "TextEncodeQwenImageEditPlus" if edit else "CLIPTextEncode"
    field = "prompt" if edit else "text"
    return {
        "template-photo": {"class_type": "LoadImage", "inputs": {"image": "NEVER-USE-TEMPLATE.png"}},
        "positive": {
            "class_type": kind,
            "inputs": {field: "template", **({"image1": ["template-photo", 0]} if edit else {})},
        },
        "negative": {
            "class_type": kind,
            "inputs": {field: "", **({"image1": ["template-photo", 0]} if edit else {})},
        },
        "canvas": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "positive": ["positive", 0],
                "negative": ["negative", 0],
                "latent_image": ["canvas", 0],
                "seed": 1,
                "steps": 4,
                "cfg": 1,
                "model": ["model", 0],
            },
        },
        "model": {"class_type": "UNETLoader", "inputs": {"unet_name": "preserve-qwen-model"}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0]}},
        "save": {
            "class_type": "SaveImage",
            "inputs": {"images": ["decode", 0], "filename_prefix": "template"},
        },
    }


class QwenRemote(Remote):
    def __init__(self):
        super().__init__()
        self.qwen = {
            EDIT_WORKFLOW: json.dumps(graph()).encode(),
            T2I_WORKFLOW: json.dumps(graph(False)).encode(),
        }
        self.identity["workflows"].update(
            {name: hashlib.sha256(raw).hexdigest() for name, raw in self.qwen.items()}
        )

    def handle(self, request):
        assert request.headers.get("authorization") == "Bearer " + TOKEN
        name = request.url.path.rsplit("/", 1)[-1]
        if name in self.qwen:
            return httpx.Response(200, content=self.qwen[name])
        if request.url.path.startswith("/history/") and self.done and self.posts:
            pid = request.url.path.rsplit("/", 1)[-1]
            post = next((p for p in self.posts if p["prompt_id"] == pid), None)
            if post and any(n["class_type"] == "SaveVideo" for n in post["prompt"].values()):
                return super().handle(request)
            return httpx.Response(
                200,
                json={
                    pid: {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {
                            "save": {
                                "images": [{"filename": "result.png", "type": "output", "subfolder": ""}]
                            }
                        },
                    }
                },
            )
        if request.url.path == "/view" and request.url.params.get("filename") == "result.png":
            return httpx.Response(200, content=png_bytes((30, 70, 120)))
        return super().handle(request)


@pytest.fixture
def qwen(monkeypatch):
    remote = QwenRemote()
    monkeypatch.setattr("frutinovelas.routes.generation.ComfyClient", remote.client)
    monkeypatch.setattr("frutinovelas.routes.images.ComfyClient", remote.client)
    return remote


def upload(client, color):
    return client.post("/api/v1/assets", files={"file": ("ref.png", png_bytes(color), "image/png")}).json()


def setup_cast(client, s):
    chapter = client.get(f"/api/v1/chapters/{s['chapter_id']}").json()
    characters = []
    for name, color in [("Darío", (20, 70, 90)), ("Bruno", (70, 20, 30))]:
        asset = upload(client, color)
        response = client.post(
            f"/api/v1/projects/{chapter['project_id']}/characters",
            json={"name": name, "description": f"{name} identity", "reference_asset_id": asset["id"]},
        )
        assert response.status_code == 201, response.text
        characters.append(response.json())
    response = client.patch(
        f"/api/v1/scenes/{s['id']}",
        json={
            "expected_revision": s["revision"],
            "parameters": {
                "character_ids": [c["id"] for c in characters],
                "image_prompt": "Literal image prompt ñ\nPose.",
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json(), characters, chapter


def submit_image(client, s, id=None):
    return client.post(
        f"/api/v1/scenes/{s['id']}/generate-image",
        json={"expected_revision": s["revision"], "request_id": id or str(uuid4())},
    )


def test_library_and_frozen_cast_preserve_literal_prompts(client):
    s, characters, chapter = setup_cast(client, scene(client))
    assert len(client.get(f"/api/v1/projects/{chapter['project_id']}/characters").json()) == 2
    assert s["prompt"] == "Darío: «Bruno, para ahí». Natural camera cut."
    assert s["parameters"]["image_prompt"] == "Literal image prompt ñ\nPose."
    original = copy.deepcopy(s["parameters"]["cast"])
    new_asset = upload(client, (90, 30, 50))
    updated = client.put(
        f"/api/v1/characters/{characters[0]['id']}",
        json={
            "name": "Darío actualizado",
            "description": "",
            "reference_asset_id": new_asset["id"],
            "expected_revision": 1,
        },
    )
    assert updated.status_code == 200, updated.text
    assert (
        client.put(
            f"/api/v1/characters/{characters[0]['id']}",
            json={"name": "Old", "reference_asset_id": new_asset["id"], "expected_revision": 1},
        ).status_code
        == 409
    )
    saved = client.patch(
        f"/api/v1/scenes/{s['id']}",
        json={
            "expected_revision": s["revision"],
            "parameters": {"seed_mode": "fixed", "seed": 3, "cast": [{"asset_id": "forged"}]},
        },
    ).json()
    assert saved["parameters"]["cast"] == original
    assert saved["parameters"]["image_prompt"] == s["parameters"]["image_prompt"]
    assert len(client.get(f"/api/v1/scenes/{s['id']}/revisions").json()) == 3


def test_cast_scope_duplicates_and_reference_limit_are_validated(client):
    s, characters, chapter = setup_cast(client, scene(client))
    other_scene = scene(client)
    body = {
        "expected_revision": other_scene["revision"],
        "parameters": {"character_ids": [characters[0]["id"]]},
    }
    assert client.patch(f"/api/v1/scenes/{other_scene['id']}", json=body).status_code == 422
    for ids in ([characters[0]["id"]] * 2, [c["id"] for c in characters] + ["third"]):
        assert (
            client.patch(
                f"/api/v1/scenes/{s['id']}",
                json={"expected_revision": s["revision"], "parameters": {"character_ids": ids}},
            ).status_code
            == 422
        )
    assert (
        client.post(
            f"/api/v1/projects/{chapter['project_id']}/characters",
            json={"name": "Darío", "reference_asset_id": characters[0]["reference_asset"]["id"]},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("count", [0, 1, 2])
def test_graph_binds_reference_tensors_and_preserves_model_sampling(count):
    source = graph(bool(count))
    original = copy.deepcopy(source)
    cast = [{"name": f"Actor{i}", "description": ""} for i in range(count)]
    prepared = prepare_image_graph(
        source, "Saved prompt", cast, 99, [f"ref{i}.png" for i in range(count)], "job"
    )
    assert source == original
    assert prepared["sampler"]["inputs"]["steps"] == 4
    assert prepared["model"] == source["model"]
    assert prepared["sampler"]["inputs"]["seed"] == 99
    assert prepared["fruti_canvas"]["inputs"] == {"width": 576, "height": 1024, "batch_size": 1}
    assert "NEVER-USE-TEMPLATE" not in json.dumps(prepared)
    for i in range(count):
        assert prepared["positive"]["inputs"][f"image{i + 1}"] == [f"fruti_reference_{i + 1}", 0]
        assert prepared["negative"]["inputs"][f"image{i + 1}"] == [f"fruti_reference_{i + 1}", 0]
        assert prepared[f"fruti_reference_{i + 1}"]["inputs"]["image"] == f"ref{i}.png"
    if count:
        assert "image3" not in prepared["positive"]["inputs"]
    with pytest.raises(ComfyError):
        prepare_image_graph(
            {"unrecognized": {"class_type": "Nothing", "inputs": {}}}, "prompt", [], 1, [], "x"
        )


def test_image_round_trip_queue_retries_approval_and_video_history(client, qwen):
    connect(client)
    s, characters, _chapter = setup_cast(client, scene(client))
    initial = s["start_asset"]["id"]
    request_id = str(uuid4())
    response = submit_image(client, s, request_id)
    assert response.status_code == 202, response.text
    assert submit_image(client, s, request_id).json()["id"] == request_id
    assert submit_image(client, s).status_code == 422
    worker = GenerationWorker(client_factory=qwen.client)
    try:
        worker.tick()
        assert len(qwen.posts) == 1 and len(qwen.uploads) == 2
        sent = qwen.posts[0]["prompt"]
        assert "Reference image 1: Darío" in sent["positive"]["inputs"]["prompt"]
        assert "Reference image 2: Bruno" in sent["positive"]["inputs"]["prompt"]
        assert client.get(f"/api/v1/scenes/{s['id']}/generations").json() == []
        qwen.done = True
        worker.tick()
    finally:
        worker.stop()
    jobs = client.get(f"/api/v1/scenes/{s['id']}/image-generations").json()
    assert jobs[0]["state"] == "completed"
    assert "graph" not in json.dumps(jobs) and TOKEN not in json.dumps(jobs)
    assert jobs[0]["references"][0]["asset_id"] == characters[0]["reference_asset"]["id"]
    assert client.get(jobs[0]["result_url"]).status_code == 200
    unchanged = client.get(f"/api/v1/scenes/{s['id']}").json()
    assert unchanged["start_asset"]["id"] == initial
    approved = client.post(
        f"/api/v1/image-generations/{request_id}/approve",
        json={"expected_revision": s["revision"], "role": "start"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["start_asset"]["id"] == jobs[0]["result_asset_id"]
    assert approved.json()["prompt"] == s["prompt"]
    assert (
        client.post(
            f"/api/v1/image-generations/{request_id}/approve", json={"expected_revision": s["revision"]}
        ).status_code
        == 409
    )


def test_uncertain_image_post_never_repeats_inference(client, qwen):
    connect(client)
    s, _characters, _chapter = setup_cast(client, scene(client))
    response = submit_image(client, s)
    qwen.lose_response = True
    worker = GenerationWorker(client_factory=qwen.client)
    try:
        worker.tick()
        with session_factory()() as session:
            assert session.get(GenerationJob, response.json()["id"]).state == "unknown"
        worker.tick()
        assert len(qwen.posts) == 1
    finally:
        worker.stop()


def test_unpublished_or_tampered_qwen_workflow_does_not_enqueue(client, qwen):
    connect(client)
    s, _characters, _chapter = setup_cast(client, scene(client))
    qwen.identity["workflows"].pop(EDIT_WORKFLOW)
    assert submit_image(client, s).status_code == 422
    assert qwen.posts == []
    qwen.identity["workflows"][EDIT_WORKFLOW] = "tampered"
    assert submit_image(client, s).status_code == 422
    assert client.get(f"/api/v1/scenes/{s['id']}/image-generations").json() == []


@pytest.mark.asyncio
async def test_mcp_reads_images_and_saves_both_prompts_through_studio_api(client, qwen, monkeypatch):
    from frutinovelas import mcp_studio
    from frutinovelas.mcp_server import create_server

    s, characters, _chapter = setup_cast(client, scene(client))

    def proxy(method, path, body=None, raw=False):
        response = (
            client.request(method, "/api/v1/" + path, json=body)
            if body is not None
            else client.request(method, "/api/v1/" + path)
        )
        if not response.is_success:
            raise ValueError(response.text)
        return response.content if raw else response.json()

    monkeypatch.setattr(mcp_studio, "studio_request", proxy)
    server = create_server()
    result = await server.call_tool("get_scene_preparation", {"scene_id": s["id"]})
    assert not result.is_error
    assert "Literal image prompt" in str(result)
    preview = await server.call_tool(
        "inspect_studio_image", {"asset_id": characters[0]["reference_asset"]["id"]}
    )
    assert not preview.is_error
    assert any(content.type == "image" for content in preview.content)
    literal = "Animated literal ñ\n<d>Hola.</d>"
    result = await server.call_tool(
        "save_scene_preparation",
        {
            "scene_id": s["id"],
            "expected_revision": s["revision"],
            "image_prompt": "New image prompt",
            "animation_prompt": literal,
            "duration_seconds": 8.5,
        },
    )
    assert not result.is_error
    updated = client.get(f"/api/v1/scenes/{s['id']}").json()
    assert updated["prompt"] == literal
    assert updated["duration_seconds"] == 8.5
    assert updated["end_asset"]["id"] == s["end_asset"]["id"]
    assert updated["parameters"]["image_prompt"] == "New image prompt"
    assert updated["parameters"]["cast"] == s["parameters"]["cast"]
    assert qwen.posts == []
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="4 y 15"):
        await server.call_tool(
            "save_scene_preparation",
            {"scene_id": s["id"], "expected_revision": updated["revision"], "duration_seconds": 16},
        )
    assert client.get(f"/api/v1/scenes/{s['id']}").json()["duration_seconds"] == 8.5


def test_image_progress_does_not_materialize_workflow_snapshots(client, qwen):
    from test_read_performance import reads

    connect(client)
    s, _characters, _chapter = setup_cast(client, scene(client))
    assert submit_image(client, s).status_code == 202
    with reads() as (loaded, statements):
        response = client.get(f"/api/v1/scenes/{s['id']}/image-generations")
    assert response.status_code == 200
    assert loaded[GenerationJob] == 0
    assert "generation_jobs.encrypted_token" not in statements[-1]
    assert "JSON_EXTRACT" in statements[-1]


def test_two_scene_images_share_one_serial_gpu_worker(client, qwen):
    connect(client)
    first, _characters, _chapter = setup_cast(client, scene(client))
    second = client.post(
        f"/api/v1/chapters/{first['chapter_id']}/scenes",
        json={"title": "Second shot", "parameters": first["parameters"]},
    ).json()
    first_job = submit_image(client, first).json()
    second_job = submit_image(client, second).json()
    worker = GenerationWorker(client_factory=qwen.client)
    try:
        worker.tick()
        worker.tick()
        assert len(qwen.posts) == 1
        assert qwen.posts[0]["prompt_id"] == first_job["id"]
        qwen.done = True
        worker.tick()
        worker.tick()
        assert len(qwen.posts) == 2
        assert qwen.posts[1]["prompt_id"] == second_job["id"]
    finally:
        worker.stop()


def test_migration_keeps_existing_video_jobs_and_credentials(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, text

    from frutinovelas.migrate import alembic_config, upgrade_to_head

    url = "sqlite:///" + str(tmp_path / "legacy.sqlite3")
    command.upgrade(alembic_config(url), "0002")
    engine = create_engine(url)
    snapshot = json.dumps({"duration": 5, "revision_number": 1, "seed": 17, "graph": {"preserve": "exactly"}})
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO projects VALUES ('p','Project','es','9:16',0,'2026-01-01','2026-01-01')")
        )
        conn.execute(
            text(
                "INSERT INTO chapters VALUES ('c','p','Chapter',1,'Guion ñ','Continuidad',1,0,'2026-01-01','2026-01-01')"
            )
        )
        conn.execute(
            text("INSERT INTO scenes VALUES ('s','c',1,NULL,'Scene','',1,'2026-01-01','2026-01-01')")
        )
        conn.execute(
            text(
                "INSERT INTO comfy_connections VALUES ('default','https://example.com','existing-encrypted-token','{}','{}','2026-01-01','2026-01-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO generation_jobs (id,scene_id,state,prompt_id,snapshot,encrypted_token,error,created_at,updated_at) VALUES ('j','s','completed','pid',:snapshot,'original-token','','2026-01-01','2026-01-01')"
            ),
            {"snapshot": snapshot},
        )
    upgrade_to_head(url)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT kind,result_asset_id,snapshot,encrypted_token FROM generation_jobs")
        ).one()
        assert tuple(row) == ("video", None, snapshot, "original-token")
        assert (
            conn.scalar(text("SELECT encrypted_token FROM comfy_connections")) == "existing-encrypted-token"
        )
        assert conn.scalar(text("SELECT script_md FROM chapters")) == "Guion ñ"
        assert conn.scalar(text("SELECT COUNT(*) FROM characters")) == 0
    engine.dispose()
