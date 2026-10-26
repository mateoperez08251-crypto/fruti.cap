"""Flow persistence, approval, recovery and authorization; no real provider calls."""
import shutil
import subprocess
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from conftest import png_bytes
from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.flow_worker import FlowWorker
from frutinovelas.models import FlowConnection, FlowJob
from frutinovelas.services import flow
from frutinovelas.services.flow_transport import FlowError, local_secret

PREFIX = "/api/v1/flow"


def initial(client, count=1):
    p = client.post("/api/v1/projects", json={"name": "Prueba Flow"}).json()
    c = client.post(f"/api/v1/projects/{p['id']}/chapters", json={"title": "Capítulo"}).json()
    scenes = [client.post(f"/api/v1/chapters/{c['id']}/scenes", json={
        "title": f"Escena {i + 1}", "prompt": "La fruta gira lentamente. Sin música.",
        "parameters": {"image_prompt": "Fruta en un balcón, iluminación cálida."},
    }).json() for i in range(count)]
    response = client.post(PREFIX + "/connect", json={"mode": "assisted", "authorized": True})
    assert response.status_code == 200, response.text
    return {"request_id": str(uuid4()), "project_id": p["id"], "chapter_id": c["id"],
            "scene_revisions": {s["id"]: s["revision"] for s in scenes}, "generation_mode": "image"}, scenes


def generate(client, payload):
    r = client.post(PREFIX + "/generate", json=payload)
    assert r.status_code == 202, r.text
    return r.json()


def job(client, job_id):
    r = client.get(PREFIX + f"/jobs/{job_id}")
    assert r.status_code == 200, r.text
    return r.json()


def import_image(client, job_id, data=None):
    return client.post(PREFIX + f"/jobs/{job_id}/import", files={"file": ("flow.png", data or png_bytes(), "image/png")})


def test_idempotence_survives_new_worker_and_scene_edits(client):
    payload, scenes = initial(client)
    first = generate(client, payload)
    FlowWorker().tick()
    client.patch(f"/api/v1/scenes/{scenes[0]['id']}", json={"expected_revision": 1, "prompt": "Nuevo texto"})
    FlowWorker().tick()
    second = generate(client, payload)
    assert second[0]["id"] == first[0]["id"]
    assert second[0]["state"] == "awaiting_import"
    assert job(client, first[0]["id"])["snapshot"]["original_prompt"] == "Fruta en un balcón, iluminación cálida."
    altered = {**payload, "automatic_approval": True}
    assert client.post(PREFIX + "/generate", json=altered).status_code == 409
    assert client.post(PREFIX + "/generate", json={**payload, "request_id": str(uuid4()), "scene_revisions": {scenes[0]['id']: 2}}).status_code == 409


def test_manual_approval_gate_and_scene_association(client):
    payload, scenes = initial(client)
    image, video = generate(client, {**payload, "generation_mode": "image_video"})
    assert video["state"] == "awaiting_approval"
    FlowWorker().tick()
    assert import_image(client, image["id"]).status_code == 200
    FlowWorker().tick()
    assert job(client, video["id"])["state"] == "awaiting_approval"
    assert client.get(f"/api/v1/scenes/{scenes[0]['id']}").json()["start_asset"] is None
    review = client.post(PREFIX + f"/jobs/{image['id']}/review", json={"expected_revision": 1, "decision": "approved"})
    assert review.status_code == 200, review.text
    current = client.get(f"/api/v1/scenes/{scenes[0]['id']}").json()
    assert current["start_asset"]["id"] == review.json()["result_asset_id"]
    assert current["prompt"] == scenes[0]["prompt"]
    frozen = job(client, video["id"])["snapshot"]
    assert frozen["references"][0]["asset_id"] == review.json()["result_asset_id"]
    assert job(client, video["id"])["state"] == "queued"


def test_rejection_keeps_original_and_cancels_dependent_video(client):
    payload, _ = initial(client)
    image, video = generate(client, {**payload, "generation_mode": "image_video"})
    assert import_image(client, image["id"]).status_code == 200
    r = client.post(PREFIX + f"/jobs/{image['id']}/review", json={"expected_revision": 1, "decision": "rejected"})
    assert r.status_code == 200
    assert job(client, video["id"])["state"] == "cancelled"
    assert client.get(r.json()["result_url"]).content == png_bytes()


def test_automatic_approval_is_explicit_and_recovers(client):
    payload, scenes = initial(client)
    image, video = generate(client, {**payload, "generation_mode": "image_video", "automatic_approval": True})
    assert import_image(client, image["id"]).status_code == 200
    FlowWorker().tick()
    FlowWorker().tick()
    assert job(client, image["id"])["approval"] == "approved"
    assert client.get(f"/api/v1/scenes/{scenes[0]['id']}").json()["revision"] == 2
    assert job(client, video["id"])["state"] == "awaiting_import"


def test_stale_approval_never_overwrites_edited_scene_or_animates_old_prompt(client):
    payload, scenes = initial(client)
    image, video = generate(client, {**payload, "generation_mode": "image_video"})
    import_image(client, image["id"])
    client.patch(f"/api/v1/scenes/{scenes[0]['id']}", json={"expected_revision": 1, "prompt": "Editado"})
    path = PREFIX + f"/jobs/{image['id']}/review"
    assert client.post(path, json={"expected_revision": 1, "decision": "approved"}).status_code == 409
    assert client.post(path, json={"expected_revision": 2, "decision": "approved"}).status_code == 200
    assert job(client, video["id"])["state"] == "failed"
    assert client.get(f"/api/v1/scenes/{scenes[0]['id']}").json()["prompt"] == "Editado"


def test_stale_auto_approval_does_not_block_other_scenes(client):
    payload, scenes = initial(client, 2)
    first_image, _, second_image, second_video = generate(client, {
        **payload, "generation_mode": "image_video", "automatic_approval": True})
    client.patch(f"/api/v1/scenes/{scenes[0]['id']}", json={"expected_revision": 1, "prompt": "Editado"})
    assert import_image(client, first_image["id"]).status_code == 200
    assert import_image(client, second_image["id"]).status_code == 200
    FlowWorker().tick()
    FlowWorker().tick()
    assert job(client, first_image["id"])["approval"] == "pending"
    assert job(client, first_image["id"])["error"]
    assert job(client, second_image["id"])["approval"] == "approved"
    assert job(client, second_video["id"])["state"] == "awaiting_import"


def test_retry_failed_image_preserves_history_and_rebinds_pending_animation(client):
    payload, _ = initial(client)
    image, video = generate(client, {**payload, "generation_mode": "image_video"})
    with session_factory()() as s:
        flow.change(s, s.get(FlowJob, image["id"]), "failed", "Fallo previo al envío.", remote_stopped=True)
        s.commit()
    rid = str(uuid4())
    url = PREFIX + f"/jobs/{image['id']}/retry"
    assert client.post(url, json={"request_id": rid}).status_code == 202
    assert client.post(url, json={"request_id": rid}).status_code == 202
    assert job(client, video["id"])["state"] == "cancelled"
    assert import_image(client, rid).status_code == 200
    assert client.post(PREFIX + f"/jobs/{rid}/review", json={"expected_revision": 1, "decision": "approved"}).status_code == 200
    with session_factory()() as s:
        successors = list(s.scalars(select(FlowJob).where(FlowJob.dependency_id == rid)))
        assert len(successors) == 1
        assert successors[0].state == "queued"
        assert successors[0].snapshot["references"][0]["asset_id"] == s.get(FlowJob, rid).result_asset_id
        assert s.get(FlowJob, image["id"]).state == "failed"


@pytest.mark.parametrize("data", [b"not an image", png_bytes()[:70], png_bytes(size=(112, 64))])
def test_invalid_or_wrong_aspect_output_never_completes(client, data):
    payload, _ = initial(client)
    j = generate(client, payload)[0]
    r = import_image(client, j["id"], data)
    assert r.status_code in (409, 422), r.text
    assert job(client, j["id"])["state"] != "completed"


def test_result_is_immutable_and_missing_file_cannot_be_approved(client):
    payload, _ = initial(client)
    j = generate(client, payload)[0]
    assert import_image(client, j["id"]).status_code == 200
    assert import_image(client, j["id"]).status_code == 200
    assert import_image(client, j["id"], png_bytes(color=(10, 20, 30))).status_code == 409
    with session_factory()() as s:
        record = s.get(FlowJob, j["id"])
        (get_settings().resolved_data_dir / record.result_path).unlink()
    assert client.post(PREFIX + f"/jobs/{j['id']}/review", json={"expected_revision": 1, "decision": "approved"}).status_code == 409
    assert client.get(PREFIX + f"/jobs/{j['id']}/content").status_code == 409


def test_plan_validates_every_scene_before_inserting(client):
    payload, scenes = initial(client, 3)
    payload["scene_revisions"][scenes[2]["id"]] = 100
    assert client.post(PREFIX + "/generate", json=payload).status_code == 409
    with session_factory()() as s:
        assert list(s.scalars(select(FlowJob))) == []


def test_chapter_order_and_assisted_lane(client):
    payload, scenes = initial(client, 3)
    payload["scene_revisions"] = dict(reversed(list(payload["scene_revisions"].items())))
    jobs = generate(client, payload)
    assert [j["scene_id"] for j in jobs] == [s["id"] for s in scenes]
    FlowWorker().tick()
    FlowWorker().tick()
    assert [job(client, j["id"])["state"] for j in jobs] == ["awaiting_import", "queued", "queued"]
    import_image(client, jobs[0]["id"])
    FlowWorker().tick()
    assert job(client, jobs[1]["id"])["state"] == "awaiting_import"


def test_safe_cancellation_and_retry_reuses_snapshot(client):
    payload, _ = initial(client)
    j = generate(client, payload)[0]
    assert client.post(PREFIX + f"/jobs/{j['id']}/cancel").json()["remote_stopped"] is True
    rid = str(uuid4())
    r = client.post(PREFIX + f"/jobs/{j['id']}/retry", json={"request_id": rid})
    assert r.status_code == 202, r.text
    assert r.json()["id"] == rid
    assert client.post(PREFIX + f"/jobs/{j['id']}/retry", json={"request_id": rid}).json()["id"] == rid
    assert job(client, rid)["snapshot"]["original_prompt"] == job(client, j["id"])["snapshot"]["original_prompt"]


class LostResponseAgent:
    posts = 0
    identity = str(uuid4())

    def request(self, method, path, body=None):
        if path == "status":
            return {"agent_id": self.identity}
        if method == "POST" and path == "jobs":
            type(self).posts += 1
            raise httpx.ReadTimeout("provider might have accepted")
        return None

    def close(self):
        pass


def remote_job(client, count=1):
    payload, _ = initial(client, count)
    with session_factory()() as s:
        c = s.get(FlowConnection, "default")
        c.mode, c.agent_id = "uia", LostResponseAgent.identity
        s.commit()
    return generate(client, payload)


def test_timeout_restart_cancel_never_reposts_or_frees_remote_reservation(client):
    LostResponseAgent.posts = 0
    jobs = remote_job(client, 2)
    for _ in range(3):
        FlowWorker(client_factory=LostResponseAgent).tick()
    assert LostResponseAgent.posts == 1
    assert job(client, jobs[0]["id"])["state"] == "unknown"
    assert job(client, jobs[1]["id"])["state"] == "queued"
    cancelled = client.post(PREFIX + f"/jobs/{jobs[0]['id']}/cancel").json()
    assert cancelled["state"] == "cancel_requested" and cancelled["remote_stopped"] is False
    assert client.post(PREFIX + f"/jobs/{jobs[0]['id']}/retry", json={"request_id": str(uuid4())}).status_code == 409
    assert client.post(PREFIX + f"/jobs/{jobs[0]['id']}/resolve", json={"confirmed_no_remote_work": False, "note": "No comprobado"}).status_code == 409


def test_disconnect_preserves_queue_and_import_recovers_uncertain_job(client):
    j = remote_job(client)[0]
    FlowWorker(client_factory=LostResponseAgent).tick()
    assert client.post(PREFIX + "/disconnect").status_code == 200
    assert job(client, j["id"])["state"] == "unknown"
    assert import_image(client, j["id"]).status_code == 200
    assert job(client, j["id"])["state"] == "completed"


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"X-Forwarded-For": "1.2.3.4"}])
def test_local_routes_reject_untrusted_origin_host_and_tunnel(client, headers):
    assert client.post(PREFIX + "/connect", json={"authorized": True}, headers=headers).status_code == 403


def test_mcp_scope_and_read_only_are_enforced_at_backend(client):
    payload, _ = initial(client)
    j = generate(client, payload)[0]
    settings = get_settings()
    headers = {"X-Fruti-Flow-Key": local_secret("mcp")}
    settings.mcp_project_id = str(uuid4())
    assert client.get(PREFIX + f"/jobs/{j['id']}", headers=headers).status_code == 403
    assert client.get(PREFIX + f"/jobs?project_id={payload['project_id']}", headers=headers).status_code == 403
    settings.mcp_project_id = payload["project_id"]
    settings.mcp_access_mode = "read_only"
    assert client.get(PREFIX + f"/jobs/{j['id']}", headers=headers).status_code == 200
    assert client.post(PREFIX + f"/jobs/{j['id']}/cancel", headers=headers).status_code == 403
    settings.mcp_access_mode = "read_write"
    assert client.post(PREFIX + f"/jobs/{j['id']}/resolve", headers=headers,
                       json={"confirmed_no_remote_work": True, "note": "Comprobado"}).status_code == 403
    assert client.get(PREFIX + f"/jobs/{j['id']}", headers={"X-Fruti-Flow-Key": "incorrect"}).status_code == 401


def test_actual_mp4_decoding_and_audio_not_selected_for_montage(client, tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/FFprobe unavailable")
    payload, scenes = initial(client)
    asset = client.post("/api/v1/assets", files={"file": ("ref.png", png_bytes(), "image/png")}).json()
    saved = client.patch(f"/api/v1/scenes/{scenes[0]['id']}", json={"expected_revision": 1, "start_asset_id": asset["id"]}).json()
    payload.update(generation_mode="video", scene_revisions={scenes[0]["id"]: saved["revision"]})
    j = generate(client, payload)[0]
    path = tmp_path / "small.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x112:r=12", "-t", "0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    r = client.post(PREFIX + f"/jobs/{j['id']}/import", files={"file": ("clip.mp4", path.read_bytes(), "video/mp4")})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "completed"
    assert r.json()["result_metadata"]["use_provider_audio_in_montage"] is False
    assert r.json()["result_metadata"]["duration_seconds"] == pytest.approx(.5, abs=.05)


def test_no_auto_connect_or_provider_capabilities_are_fabricated(client, monkeypatch):
    from frutinovelas.routes import flow as routes
    monkeypatch.setattr(routes, "agent_status", lambda: {"available": False, "modes": {}, "authentication": "unknown"})
    assert client.post(PREFIX + "/connect", json={"mode": "uia", "authorized": True}).status_code == 409
    assert client.post(PREFIX + "/connect", json={"mode": "assisted", "authorized": False}).status_code == 422


@pytest.mark.parametrize("response", [None, {}, httpx.ConnectError("offline"), ValueError("invalid JSON")])
def test_detection_explains_unreachable_agent_without_claiming_the_window_is_closed(client, monkeypatch, response):
    from frutinovelas.routes import flow as routes
    closed = []

    class UnavailableAgent:
        def request(self, *_):
            if isinstance(response, Exception):
                raise response
            return response

        def close(self):
            closed.append(True)

    monkeypatch.setattr(routes, "FlowClient", UnavailableAgent)
    r = client.get(PREFIX + "/detect")
    assert r.status_code == 200, r.text
    assert r.json()["reachable"] is False
    assert r.json()["window_open"] is None
    assert "iniciar_flow_agente.cmd" in r.json()["detail"]
    assert closed == [True]


def test_detection_distinguishes_a_reachable_agent_without_profile(client, monkeypatch):
    from frutinovelas.routes import flow as routes

    class UnconfiguredAgent:
        def request(self, *_):
            return {"available": False, "window_open": None, "flow_available": None, "authentication": "unknown",
                    "profile_configured": False, "modes": {}, "detail": "Falta configurar el perfil."}

        def close(self):
            pass

    monkeypatch.setattr(routes, "FlowClient", UnconfiguredAgent)
    for url in ("/detect", "/status"):
        r = client.get(PREFIX + url)
        assert r.status_code == 200
        result = r.json()["agent"] if url == "/status" else r.json()
        assert result["reachable"] is True
        assert result["profile_configured"] is False
        assert result["window_open"] is None


def test_detection_handles_agent_credential_initialization_failure(client, monkeypatch):
    from frutinovelas.routes import flow as routes

    def unavailable_client():
        raise FlowError("La credencial está ocupada.")

    monkeypatch.setattr(routes, "FlowClient", unavailable_client)
    r = client.get(PREFIX + "/detect")
    assert r.status_code == 200
    assert r.json()["reachable"] is False
    assert r.json()["window_open"] is None


def test_flow_lock_serializes_multiple_backend_processes(client):
    payload, _ = initial(client)
    with flow.operation_lock(), pytest.raises(FlowError):
        FlowWorker().tick()
    assert generate(client, payload)


def test_remote_result_download_is_verified_without_resubmission(client):
    import hashlib
    class DownloadAgent(LostResponseAgent):
        complete = False
        job_id = None

        def request(self, method, path, body=None):
            if path == "status":
                return {"agent_id": self.identity}
            if method == "POST":
                type(self).posts += 1
                type(self).job_id = body["request_id"]
            return {"id": self.job_id, "agent_id": self.identity,
                    "state": "completed" if self.complete else "running", "sha256": hashlib.sha256(png_bytes()).hexdigest()}

        def download(self, job_id, destination, limit):
            assert job_id == self.job_id and limit > len(png_bytes())
            destination.write_bytes(png_bytes())

    j = remote_job(client)[0]
    DownloadAgent.posts = 0
    FlowWorker(client_factory=DownloadAgent).tick()
    assert job(client, j["id"])["state"] == "running"
    DownloadAgent.complete = True
    FlowWorker(client_factory=DownloadAgent).tick()
    finished = job(client, j["id"])
    assert finished["state"] == "completed" and DownloadAgent.posts == 1
    assert client.get(finished["result_url"]).content == png_bytes()


def test_known_agent_rejection_does_not_strand_the_queue(client):
    from frutinovelas.services.flow_transport import FlowRejected
    class RejectAgent(LostResponseAgent):
        def request(self, method, path, body=None):
            if method == "POST":
                raise FlowRejected("Duración incompatible.")
            return super().request(method, path, body)
    jobs = remote_job(client, 2)
    FlowWorker(client_factory=RejectAgent).tick()
    assert job(client, jobs[0]["id"])["state"] == "failed"
    assert job(client, jobs[0]["id"])["remote_stopped"] is True
    FlowWorker(client_factory=RejectAgent).tick()
    assert job(client, jobs[1]["id"])["state"] == "failed"
