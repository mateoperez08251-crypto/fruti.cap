"""Controlar Studio vía MCP usando la API real y sin GPU ni servicios externos."""
from uuid import uuid4

import pytest

from frutinovelas.mcp_controls import queue_chapter_images, queue_full_chapter


@pytest.mark.parametrize("prior, expected", [
    ([{"state": "cancelled"}], "queued"),
    ([{"state": "failed"}, {"state": "running"}], "existing_active"),
])
def test_batch_retries_cancelled_but_respects_older_legitimate_jobs(prior, expected):
    calls = []
    def request(method, path, body=None):
        calls.append(path)
        if path == "comfy/queue/recover":
            return {"status": "ok"}
        if path.endswith("/scenes"):
            return [{"id": "s", "title": "Irena", "revision": 1, "parameters": {"image_prompt": "Literal ñ"}}]
        if path.endswith("/image-generations"):
            return prior
        if path.endswith("/generate-image"):
            return {"id": body["request_id"], "state": "queued"}
        raise AssertionError(path)
    result = queue_chapter_images("c", str(uuid4()), request)
    assert calls[0] == "comfy/queue/recover"
    assert result["results"][0]["action"] == expected


def test_batch_image_queues_missing_only_and_retries_are_safe():
    chapter = "chapter-real"
    scenes = [
        {"id": "scene1", "title": "Uno", "revision": 1, "parameters": {"image_prompt": "Frame one"}},
        {"id": "scene2", "title": "Dos", "revision": 2, "parameters": {"image_prompt": "Frame two"}},
        {"id": "scene3", "title": "Tres", "revision": 3, "parameters": {"image_prompt": "Frame three"}},
    ]
    calls = []
    def request(method, path, body=None):
        calls.append((method, path, body))
        if path == "comfy/queue/recover":
            return {"status": "ok", "recovered": []}
        if path.endswith("/scenes") and method == "GET":
            return scenes
        if path.endswith("scene1/image-generations"):
            return [{"state": "completed"}]
        if path.endswith("scene2/image-generations"):
            return [{"state": "running"}]
        if path.endswith("scene3/image-generations") and method == "GET":
            return []
        if path.endswith("scene3/generate-image") and method == "POST":
            return {"id": body["request_id"], "state": "queued"}
        raise AssertionError(path)
    uid = str(uuid4())
    first = queue_chapter_images(chapter, uid, request)
    second = queue_chapter_images(chapter, uid, request)
    assert first["enqueued"] == 1
    assert [x["action"] for x in first["results"]] == ["existing_result", "existing_active", "queued"]
    ids = [body["request_id"] for method, path, body in calls if path.endswith("generate-image")]
    assert len(ids) == 2 and ids[0] == ids[1]
    assert all(not (path.endswith("/generate") or path.endswith("/render")) for _, path, _ in calls)


def test_batch_rejects_missing_prompt_before_submitting():
    scenes = [
        {"id": "a", "title": "Uno", "revision": 1, "parameters": {"image_prompt": "test"}},
        {"id": "b", "title": "Dos", "revision": 1, "parameters": {"image_prompt": ""}},
    ]
    calls = []
    def request(method, path, body=None):
        calls.append((method, path))
        if path == "comfy/queue/recover":
            return {"status": "ok", "recovered": []}
        if path.endswith("/scenes"):
            return scenes
        if path.endswith("image-generations"):
            return []
        raise AssertionError(path)
    with pytest.raises(Exception, match="Dos"):
        queue_chapter_images("chapter", str(uuid4()), request)
    assert not any(p.endswith("generate-image") for _, p in calls)


def test_full_chapter_requires_explicit_approval_and_includes_revisions():
    calls = []
    def request(method, path, body=None):
        calls.append((method, path, body))
        if path == "comfy/queue/recover":
            return {"status": "ok", "recovered": []}
        if path == "chapters/c":
            return {"id": "c", "revision": 5}
        if path == "chapters/c/scenes":
            return [{"id": "s", "title": "escena", "revision": 6, "prompt": "animate",
                     "duration_seconds": 7, "parameters": {"image_prompt": "visual"}}]
        if path == "chapters/c/renders":
            return []
        if path == "chapters/c/render":
            return {"id": body["request_id"], "state": "queued"}
        raise AssertionError(path)
    with pytest.raises(Exception, match="automatic_approval"):
        queue_full_chapter("c", str(uuid4()), False, request)
    assert calls == []
    answer = queue_full_chapter("c", str(uuid4()), True, request)
    assert answer["state"] == "queued"
    sent = next(body for m, p, body in calls if p == "chapters/c/render")
    assert sent["scene_revisions"] == {"s": 6}
    assert sent["expected_revision"] == 5
    assert sent["automatic_approval"] is True


@pytest.mark.asyncio
async def test_mcp_uses_real_studio_api_for_editing_and_video_status(client, monkeypatch):
    from frutinovelas import mcp_studio
    from frutinovelas.mcp_server import create_server

    project = client.post("/api/v1/projects", json={"name": "Original"}).json()

    def proxy(method, path, body=None, raw=False):
        resp = client.request(method, "/api/v1/" + path, json=body)
        resp.raise_for_status()
        return resp.content if raw else resp.json()

    monkeypatch.setattr(mcp_studio, "studio_request", proxy)
    mcp = create_server()
    r = await mcp.call_tool("update_studio_project",
        {"project_id": project["id"], "name": "Renombrado"})
    assert not r.is_error
    assert client.get(f"/api/v1/projects/{project['id']}").json()["name"] == "Renombrado"

    chapter = client.post(f"/api/v1/projects/{project['id']}/chapters",
                          json={"title": "Caso de prueba"}).json()
    result = await mcp.call_tool("create_studio_scene", {
        "chapter_id": chapter["id"], "title": "Escena uno",
        "image_prompt": "Portrait scene", "animation_prompt": "Observe surroundings",
        "duration_seconds": 6,
    })
    assert not result.is_error
    scene = client.get(f"/api/v1/chapters/{chapter['id']}/scenes").json()[0]
    assert scene["parameters"]["image_prompt"] == "Portrait scene"
    assert scene["prompt"] == "Observe surroundings"
    assert scene["duration_seconds"] == 6
    with pytest.raises(Exception, match="confirmed=true"):
        await mcp.call_tool("delete_studio_scene", {"scene_id": scene["id"]})
    assert len(client.get(f"/api/v1/chapters/{chapter['id']}/scenes").json()) == 1
