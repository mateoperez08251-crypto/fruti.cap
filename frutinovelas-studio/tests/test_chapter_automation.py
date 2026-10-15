"""Optional automation: restart-safe approval, serial GPU jobs and a real FFmpeg merge."""

import json
import subprocess
import threading
from uuid import uuid4

import pytest

from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.models import GenerationJob
from frutinovelas.services.chapter_render import assemble, ffmpeg_tools
from frutinovelas.services.image_generation import finish_automatic_image, video_request_id
from frutinovelas.worker import GenerationWorker
from test_character_images import QwenRemote, setup_cast
from test_generation import connect, scene


@pytest.fixture
def qwen(monkeypatch):
    remote = QwenRemote()
    for route in ("generation", "images", "renders"):
        monkeypatch.setattr(f"frutinovelas.routes.{route}.ComfyClient", remote.client)
    return remote


def automatic_scene(client):
    s, _, chapter = setup_cast(client, scene(client))
    response = client.patch(
        f"/api/v1/scenes/{s['id']}",
        json={"expected_revision": s["revision"], "parameters": {"image_approval": "automatic"}},
    )
    assert response.status_code == 200
    return response.json(), chapter


def test_automatic_image_approval_and_animation_resume_once_preserve_end(client, qwen):
    connect(client)
    s, _ = automatic_scene(client)
    request_id = str(uuid4())
    response = client.post(
        f"/api/v1/scenes/{s['id']}/generate-image",
        json={"expected_revision": s["revision"], "request_id": request_id, "auto_animate": True},
    )
    assert response.status_code == 202, response.text
    worker = GenerationWorker(client_factory=qwen.client)
    try:
        worker.tick()
        qwen.done = True
        worker.tick()
    finally:
        worker.stop()
    # Simulate restart between download, attachment and video POST.
    finish_automatic_image(session_factory(), request_id)
    finish_automatic_image(session_factory(), request_id)
    updated = client.get(f"/api/v1/scenes/{s['id']}").json()
    assert updated["revision"] == s["revision"] + 1
    assert updated["end_asset"]["id"] == s["end_asset"]["id"]
    with session_factory()() as db:
        image = db.get(GenerationJob, request_id)
        video = db.get(GenerationJob, video_request_id(request_id))
        assert video.snapshot["start_asset_id"] == image.result_asset_id
        assert video.snapshot["end_asset_id"] == s["end_asset"]["id"]
        assert video.snapshot["prompt"] == s["prompt"]
        assert image.snapshot["auto_finish_done"]
    restarted = GenerationWorker(client_factory=qwen.client)
    try:
        restarted.tick()
        restarted.tick()
        assert len(qwen.posts) == 2
        assert (
            client.get(f"/api/v1/generations/{video_request_id(request_id)}").json()["state"] == "completed"
        )
    finally:
        restarted.stop()


def test_auto_approval_stops_on_edit_without_overwriting_or_animating(client, qwen):
    connect(client)
    s, _ = automatic_scene(client)
    client.post(
        f"/api/v1/scenes/{s['id']}/generate-image",
        json={"expected_revision": s["revision"], "request_id": str(uuid4()), "auto_animate": True},
    ).json()
    worker = GenerationWorker(client_factory=qwen.client)
    try:
        worker.tick()
        changed = client.patch(
            f"/api/v1/scenes/{s['id']}",
            json={"expected_revision": s["revision"], "prompt": "Keep this new dialogue"},
        ).json()
        qwen.done = True
        worker.tick()
        worker.tick()
    finally:
        worker.stop()
    latest = client.get(f"/api/v1/scenes/{s['id']}").json()
    assert latest["revision"] == changed["revision"]
    assert latest["prompt"] == "Keep this new dialogue"
    assert latest["start_asset"]["id"] == s["start_asset"]["id"]
    jobs = client.get(f"/api/v1/scenes/{s['id']}/image-generations").json()
    assert jobs[0]["result_asset_id"] and "detenida" in jobs[0]["error"]
    assert client.get(f"/api/v1/scenes/{s['id']}/generations").json() == []
    assert len(qwen.posts) == 1


def test_manual_default_cannot_implicitly_start_video(client, qwen):
    connect(client)
    s, _, _ = setup_cast(client, scene(client))
    assert s["parameters"]["image_approval"] == "manual"
    response = client.post(
        f"/api/v1/scenes/{s['id']}/generate-image",
        json={"expected_revision": s["revision"], "request_id": str(uuid4()), "auto_animate": True},
    )
    assert response.status_code == 422
    assert qwen.posts == []


def request_run(client, chapter, scenes, id=None, **overrides):
    return client.post(
        f"/api/v1/chapters/{chapter['id']}/render",
        json={
            "request_id": id or str(uuid4()),
            "expected_revision": chapter["revision"],
            "scene_revisions": {s["id"]: s["revision"] for s in scenes},
            "automatic_approval": True,
            **overrides,
        },
    )


def test_chapter_preflight_and_explicit_opt_in_before_any_gpu_submission(client, qwen, monkeypatch):
    monkeypatch.setattr("frutinovelas.routes.renders.ComfyClient", qwen.client)
    connect(client)
    s, _, chapter = setup_cast(client, scene(client))
    assert request_run(client, chapter, [s], automatic_approval=False).status_code == 422
    assert request_run(client, chapter, [s], scene_revisions={s["id"]: 999}).status_code == 422
    missing = client.patch(
        f"/api/v1/scenes/{s['id']}", json={"expected_revision": s["revision"], "prompt": ""}
    ).json()
    assert request_run(client, chapter, [missing]).status_code == 422
    assert qwen.posts == []


def test_chapter_serial_pipeline_recovers_and_returns_single_result(client, qwen, monkeypatch):
    monkeypatch.setattr("frutinovelas.routes.renders.ComfyClient", qwen.client)
    connect(client)
    first, _, chapter = setup_cast(client, scene(client))
    second = client.post(
        f"/api/v1/chapters/{chapter['id']}/scenes",
        json={
            "title": "Reply",
            "prompt": "Second literal prompt",
            "duration_seconds": 7,
            "parameters": first["parameters"],
            "end_asset_id": first["end_asset"]["id"],
            "start_asset_id": first["start_asset"]["id"],
        },
    ).json()
    merged = []

    def fake_assemble(id, paths, stop):
        merged.append(list(paths))
        path = get_settings().exports_dir / (id + ".mp4")
        path.write_bytes(b"combined")
        return path

    monkeypatch.setattr("frutinovelas.services.chapter_render.assemble", fake_assemble)
    id = str(uuid4())
    response = request_run(client, chapter, [first, second], id)
    assert response.status_code == 202, response.text
    assert request_run(client, chapter, [first, second], id).json()["id"] == id
    assert qwen.posts == []
    qwen.done = True
    worker = GenerationWorker(client_factory=qwen.client)
    try:
        for _ in range(20):
            worker.tick()
            runs = client.get(f"/api/v1/chapters/{chapter['id']}/renders").json()
            if runs[0]["state"] in ("completed", "failed"):
                break
        assert runs[0]["state"] == "completed", runs
    finally:
        worker.stop()
    assert len(qwen.posts) == 4
    assert [any(n["class_type"] == "SaveVideo" for n in p["prompt"].values()) for p in qwen.posts] == [
        False,
        True,
        False,
        True,
    ]
    assert [p["prompt"]["28"]["inputs"]["value"] for p in qwen.posts if "28" in p["prompt"]] == [5, 7]
    assert len(merged) == 1 and len(merged[0]) == 2
    assert client.get(runs[0]["result_url"]).content == b"combined"
    for original in (first, second):
        updated = client.get(f"/api/v1/scenes/{original['id']}").json()
        assert updated["end_asset"]["id"] == original["end_asset"]["id"]


def test_chapter_stops_if_future_scene_changes(client, qwen, monkeypatch):
    monkeypatch.setattr("frutinovelas.routes.renders.ComfyClient", qwen.client)
    connect(client)
    s, _, chapter = setup_cast(client, scene(client))
    assert request_run(client, chapter, [s]).status_code == 202
    worker = GenerationWorker(client_factory=qwen.client)
    try:
        worker.tick()  # preflight queues the image, but no GPU POST yet
        client.patch(
            f"/api/v1/scenes/{s['id']}", json={"expected_revision": s["revision"], "prompt": "Changed"}
        )
        worker.tick()
        qwen.done = True
        worker.tick()
        worker.tick()
        run = client.get(f"/api/v1/chapters/{chapter['id']}/renders").json()[0]
        assert run["state"] == "failed"
        assert len(qwen.posts) == 1
        assert client.get(f"/api/v1/scenes/{s['id']}/generations").json() == []
    finally:
        worker.stop()


def test_ffmpeg_merges_actual_audio_and_silent_clips(data_dir):
    settings = get_settings()
    settings.ensure_dirs()
    ffmpeg, probe = ffmpeg_tools()
    paths = []
    for i in range(2):
        path = settings.tmp_dir / f"clip-{i}.mp4"
        args = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={'red' if i else 'blue'}:s=144x256:r=24:d=0.5",
        ]
        if i == 0:
            args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=0.5", "-c:a", "aac", "-shortest"]
        args += ["-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(path)]
        subprocess.run(args, capture_output=True, check=True)
        paths.append(path)
    result = assemble(str(uuid4()), paths, threading.Event())
    info = json.loads(
        subprocess.run(
            [probe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(result)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert {s["codec_type"] for s in info["streams"]} == {"audio", "video"}
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (576, 1024)
    assert 0.95 <= float(info["format"]["duration"]) <= 1.2
    assert all(p.is_file() for p in paths)
