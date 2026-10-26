import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from conftest import png_bytes
from frutinovelas.db import session_factory
from frutinovelas.models import Asset, Chapter, FlowJob
from frutinovelas.services import narrated_automation as automation


def initial_video(client, mode="static", references=None):
    project = client.post("/api/v1/projects", json={"name": "Narración automática"}).json()
    with session_factory()() as session:
        audio = Asset(kind="narration", rel_path="assets/master.wav", sha256="a" * 64,
                      mime="audio/wav", duration_seconds=12, size_bytes=10, original_name="voz.wav")
        session.add(audio)
        session.commit()
        audio_id = audio.id
    response = client.post(f"/api/v1/projects/{project['id']}/narrated-videos", json={
        "title": "Prueba", "audio_asset_id": audio_id, "transcript": "Una fruta entra. Después mira el cielo.",
        "aspect_ratio": "16:9", "shots": [{
            "start_seconds": 0, "end_seconds": 12, "text": "Texto original",
            "image_prompt": " Fruta bajo el sol.\r\n", "animation_prompt": " Mira arriba.\n",
            "motion": "still", "media_mode": mode, "references": references or [],
        }],
    })
    assert response.status_code == 201, response.text
    client.post("/api/v1/flow/connect", json={"mode": "assisted", "authorized": True})
    return response.json()


def test_dispatch_preserves_references_prompt_ratio_and_repeated_request(client):
    asset = client.post("/api/v1/assets", files={"file": ("style.png", png_bytes(), "image/png")}).json()
    video = initial_video(client, references=[{"asset_id": asset["id"], "role": "style", "description": "Luz cálida"}])
    path = f"/api/v1/narrated-videos/{video['id']}/flow"
    body = {"expected_revision": 1, "request_id": str(uuid4())}
    first = client.post(path, json=body)
    assert first.status_code == 202, first.text
    second = client.post(path, json=body)
    assert second.status_code == 202, second.text
    result = first.json()
    assert result["jobs"][0]["id"] == second.json()["jobs"][0]["id"]
    assert result["video"]["shots"][0]["references"][0]["role"] == "style"
    with session_factory()() as session:
        jobs = list(session.scalars(select(FlowJob)))
        assert len(jobs) == 1
        assert result["video"]["flow_chapter_id"] == jobs[0].chapter_id
        assert jobs[0].snapshot["prompt"] == " Fruta bajo el sol.\r\n"
        assert jobs[0].snapshot["aspect_ratio"] == "16:9"
        assert jobs[0].snapshot["references"] == [{"asset_id": asset["id"], "sha256": asset["sha256"]}]
        assert len(list(session.scalars(select(Chapter)))) == 1
    assert client.post(path, json={**body, "clip_seconds": 8}).status_code == 409


def test_animated_dispatch_waits_for_image_approval_and_locks_duplicate_dispatch(client):
    video = initial_video(client, "animated")
    path = f"/api/v1/narrated-videos/{video['id']}/flow"
    response = client.post(path, json={"expected_revision": 1, "request_id": str(uuid4())})
    assert response.status_code == 202, response.text
    result = response.json()
    assert [job["kind"] for job in result["jobs"]] == ["image", "video"]
    assert result["jobs"][1]["state"] == "awaiting_approval"
    assert result["video"]["shots"][0]["flow_video_job_id"] == result["jobs"][1]["id"]
    assert client.post(path, json={"expected_revision": 2, "request_id": str(uuid4())}).status_code == 409
    assert client.post(f"/api/v1/narrated-videos/{video['id']}/render", json={"expected_revision": 2}).status_code == 422


def test_invalid_reference_rejects_entire_dispatch_without_chapter_or_jobs(client):
    video = initial_video(client)
    with session_factory()() as session:
        from frutinovelas.models import NarratedVideo
        row = session.get(NarratedVideo, video["id"])
        row.shots = [{**row.shots[0], "references": [{"asset_id": str(uuid4()), "role": "style"}]}]
        session.commit()
    response = client.post(f"/api/v1/narrated-videos/{video['id']}/flow", json={"expected_revision": 1, "request_id": str(uuid4())})
    assert response.status_code == 409
    with session_factory()() as session:
        assert not list(session.scalars(select(FlowJob)))
        assert not list(session.scalars(select(Chapter)))


def test_sync_links_verified_image_and_keeps_audio_timeline(client):
    video = initial_video(client)
    response = client.post(f"/api/v1/narrated-videos/{video['id']}/flow", json={"expected_revision": 1, "request_id": str(uuid4())}).json()
    job_id = response["jobs"][0]["id"]
    imported = client.post(f"/api/v1/flow/jobs/{job_id}/import", files={"file": ("image.png", png_bytes(size=(160, 90)), "image/png")})
    assert imported.status_code == 200, imported.text
    synced = client.post(f"/api/v1/narrated-videos/{video['id']}/sync", json={"expected_revision": 2})
    assert synced.status_code == 200, synced.text
    result = synced.json()["video"]
    assert result["shots"][0]["image_asset_id"] == imported.json()["result_asset_id"]
    assert result["audio_asset_id"] == video["audio_asset_id"]
    assert result["shots"][0]["end_seconds"] == 12
    assert result["transcript"] == video["transcript"]


def test_planner_sends_selected_reference_and_uses_complete_audio_timeline(client, monkeypatch):
    video = initial_video(client)
    raw = png_bytes()
    asset = client.post("/api/v1/assets", files={"file": ("identity.png", raw, "image/png")}).json()
    calls = []

    class PlannerClient:
        def __init__(self, *args, **kwargs):
            pass

        def _request(self, *args):
            calls.append(args[2])
            return {"choices": [{"message": {"content": json.dumps({"shots": [
                {"text": "Una fruta entra.", "image_prompt": "Fruta entrando", "weight": 1},
                {"text": "Después mira el cielo.", "image_prompt": "Fruta mirando", "weight": 2},
            ]})}}]}

        def close(self):
            pass

    monkeypatch.setattr(automation, "VisionClient", PlannerClient)
    monkeypatch.setattr(automation, "load_connection", lambda: SimpleNamespace(base_url="https://qwen.example/v1", api_key="test", model="verified-alias"))
    response = client.post(f"/api/v1/narrated-videos/{video['id']}/plan", json={
        "expected_revision": 1, "shot_count": 2, "references": [{"asset_id": asset["id"], "role": "identity"}],
        "visual_style": "Acuarela luminosa",
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["transcript"] == video["transcript"]
    assert result["shots"][0]["start_seconds"] == 0
    assert result["shots"][0]["end_seconds"] == result["shots"][1]["start_seconds"]
    assert result["shots"][-1]["end_seconds"] == 12
    assert result["shots"][0]["motion"] == "still"
    assert result["shots"][0]["references"][0]["asset_id"] == asset["id"]
    assert calls[0]["model"] == "verified-alias" and calls[0]["stream"] is False
    assert calls[0]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert hashlib.sha256(raw).hexdigest() == asset["sha256"]


def test_foreign_flow_results_are_rejected_when_saving(client):
    first = initial_video(client)
    result = client.post(f"/api/v1/narrated-videos/{first['id']}/flow", json={"expected_revision": 1, "request_id": str(uuid4())}).json()
    # Another project cannot attach a Flow job from the first project.
    project = client.post("/api/v1/projects", json={"name": "Otro"}).json()
    second = client.post(f"/api/v1/projects/{project['id']}/narrated-videos", json={
        "title": "Otra narración", "audio_asset_id": first["audio_asset_id"],
    }).json()
    response = client.patch(f"/api/v1/narrated-videos/{second['id']}", json={
        "expected_revision": 1, "shots": result["video"]["shots"],
    })
    assert response.status_code == 422


def test_can_animate_an_existing_approved_static_image_without_regenerating_it(client):
    video = initial_video(client)
    response = client.post(f"/api/v1/narrated-videos/{video['id']}/flow", json={"expected_revision": 1, "request_id": str(uuid4())}).json()
    image_id = response["jobs"][0]["id"]
    imported = client.post(f"/api/v1/flow/jobs/{image_id}/import", files={"file": ("image.png", png_bytes(size=(160, 90)), "image/png")})
    assert imported.status_code == 200, imported.text
    assert client.post(f"/api/v1/flow/jobs/{image_id}/review", json={"expected_revision": 1, "decision": "approved"}).status_code == 200
    synced = client.post(f"/api/v1/narrated-videos/{video['id']}/sync", json={"expected_revision": 2}).json()["video"]
    shots = [{**shot, "media_mode": "animated", "animation_prompt": " La fruta saluda.\n"} for shot in synced["shots"]]
    saved = client.patch(f"/api/v1/narrated-videos/{video['id']}", json={"expected_revision": synced["revision"], "shots": shots}).json()
    body = {"expected_revision": saved["revision"], "request_id": str(uuid4()), "clip_seconds": 5}
    path = f"/api/v1/narrated-videos/{video['id']}/animate"
    first = client.post(path, json=body)
    assert first.status_code == 202, first.text
    assert client.post(path, json=body).json()["jobs"][0]["id"] == first.json()["jobs"][0]["id"]
    with session_factory()() as session:
        jobs = list(session.scalars(select(FlowJob)))
        assert len(jobs) == 2
        clip = next(job for job in jobs if job.kind == "video")
        assert clip.snapshot["prompt"] == " La fruta saluda.\n"
        assert clip.snapshot["references"][0]["asset_id"] == imported.json()["result_asset_id"]


def test_narrated_actions_obey_mcp_project_scope_and_read_only_mode(client):
    from frutinovelas.config import get_settings
    from frutinovelas.services.flow_transport import local_secret
    video = initial_video(client)
    headers = {"X-Fruti-Flow-Key": local_secret("mcp")}
    settings = get_settings()
    settings.mcp_project_id = str(uuid4())
    url = f"/api/v1/narrated-videos/{video['id']}/sync"
    assert client.post(url, json={"expected_revision": 1}, headers=headers).status_code == 403
    settings.mcp_project_id = video["project_id"]
    settings.mcp_access_mode = "read_only"
    assert client.post(url, json={"expected_revision": 1}, headers=headers).status_code == 403


def test_reference_images_cannot_be_discarded_while_used_in_narration(client):
    from frutinovelas.models import GenerationJob
    asset = client.post("/api/v1/assets", files={"file": ("style.png", png_bytes(), "image/png")}).json()
    video = initial_video(client, references=[{"asset_id": asset["id"], "role": "style"}])
    dispatch = client.post(f"/api/v1/narrated-videos/{video['id']}/flow", json={"expected_revision": 1, "request_id": str(uuid4())}).json()
    scene_id = dispatch["jobs"][0]["scene_id"]
    with session_factory()() as session:
        generation = GenerationJob(scene_id=scene_id, kind="image", state="completed", prompt_id="test",
                                   snapshot={}, encrypted_token="", result_asset_id=asset["id"])
        session.add(generation)
        session.commit()
        identifier = generation.id
    response = client.delete(f"/api/v1/generations/{identifier}/output")
    assert response.status_code == 409, response.text


def test_storyboard_choice_survives_dispatch_and_agent_payload(client):
    from frutinovelas.services.flow import agent_payload
    video = initial_video(client)
    changed = client.patch(f"/api/v1/narrated-videos/{video['id']}", json={
        "expected_revision": 1, "shots": [{**shot, "flow_tool": "storyboard_studio"} for shot in video["shots"]],
    }).json()
    response = client.post(f"/api/v1/narrated-videos/{video['id']}/flow", json={
        "expected_revision": changed["revision"], "request_id": str(uuid4()),
    })
    assert response.status_code == 202, response.text
    with session_factory()() as session:
        job = session.get(FlowJob, response.json()["jobs"][0]["id"])
        assert job.snapshot["flow_tool"] == "storyboard_studio"
        assert agent_payload(session, job)["flow_tool"] == "storyboard_studio"
