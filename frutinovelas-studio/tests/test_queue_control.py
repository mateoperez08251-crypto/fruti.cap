"""Safe targeted ComfyUI queue controls, with isolated mocked remote gateway."""
from uuid import uuid4

import pytest
from frutinovelas.db import session_factory
from frutinovelas.models import GenerationJob
from frutinovelas.services.comfy import ComfyError
from frutinovelas.services.queue_control import list_queue, stop_job, queue_ids
from test_generation import connect, scene, submit, Remote


class QueueClient:
    def __init__(self, remote):
        self.remote = remote
    def get(self, path):
        if path == "/frutinovelas/identity":
            return self.remote.identity
        if path == "/queue":
            return self.remote.queue
        raise AssertionError(path)
    def request(self, method, path, json=None):
        self.remote.calls.append((method, path, json))
        if path == "/queue":
            self.remote.queue["queue_pending"] = [e for e in self.remote.queue["queue_pending"] if e[1] not in json["delete"]]
        if path == "/interrupt":
            self.remote.queue["queue_running"] = []
        return {}
    def close(self):
        pass


def setup(client):
    remote = Remote()
    # Connection saves the immutable runtime identity, no actual GPU execution.
    from frutinovelas.services.comfy import ComfyClient
    import httpx
    from unittest.mock import patch
    with patch("frutinovelas.routes.generation.ComfyClient", remote.client):
        connect(client)
    s = scene(client)
    with patch("frutinovelas.routes.generation.ComfyClient", remote.client):
        result = submit(client, s)
    assert result.status_code == 202, result.text
    return result.json()["id"], remote


def test_queue_ids_ignores_unrelated_metadata():
    assert queue_ids({"queue_running": [[0, "job-a", {}]], "queue_pending": [[1, "job-b", {}]]}) == (["job-a"], ["job-b"])


def test_queued_stop_no_remote_request(client):
    id, remote = setup(client)
    response = client.post(f"/api/v1/generations/{id}/stop")
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "cancelled"
    assert client.post(f"/api/v1/generations/{id}/stop").json()["already_stopped"]
    with session_factory()() as db:
        assert db.get(GenerationJob, id).active_scene_id is None


def test_targeted_pending_cancel_and_other_pending_preserved(client):
    id, remote = setup(client)
    with session_factory()() as db:
        job = db.get(GenerationJob, id)
        job.state, job.prompt_id = "waiting", id
        db.commit()
    remote.queue = {"queue_running": [], "queue_pending": [[1, id, {}], [2, "foreign", {}]]}
    remote.calls = []
    from unittest.mock import patch
    with patch("frutinovelas.services.queue_control.ComfyClient", lambda *args: QueueClient(remote)):
        output = client.post(f"/api/v1/generations/{id}/stop")
    assert output.status_code == 200, output.text
    assert output.json()["remote_action"] == "removed_pending"
    assert remote.queue["queue_pending"][0][1] == "foreign"
    assert remote.calls == [("POST", "/queue", {"delete": [id]})]


def test_running_interrupt_requires_only_one_job(client):
    id, remote = setup(client)
    with session_factory()() as db:
        job = db.get(GenerationJob, id)
        job.state = "running"
        db.commit()
    remote.queue = {"queue_running": [[1, "foreign"], [2, id]], "queue_pending": []}
    remote.calls = []
    from unittest.mock import patch
    with patch("frutinovelas.services.queue_control.ComfyClient", lambda *args: QueueClient(remote)):
        denied = client.post(f"/api/v1/generations/{id}/stop")
    assert denied.status_code == 409
    assert not remote.calls
    remote.queue["queue_running"] = [[1, id]]
    with patch("frutinovelas.services.queue_control.ComfyClient", lambda *args: QueueClient(remote)):
        ok = client.post(f"/api/v1/generations/{id}/stop")
    assert ok.status_code == 200, ok.text
    assert ok.json()["state"] == "stopping"
    assert remote.calls == [("POST", "/interrupt", {})]
    with session_factory()() as db:
        assert db.get(GenerationJob, id).snapshot["stop_requested"]


def test_queue_read_never_exposes_other_prompts(client):
    id, remote = setup(client)
    remote.queue = {"queue_running": [], "queue_pending": [[1, "unrelated", {}]]}
    from unittest.mock import patch
    with patch("frutinovelas.services.queue_control.ComfyClient", lambda *args: QueueClient(remote)):
        result = client.get("/api/v1/comfy/queue")
    assert result.status_code == 200, result.text
    assert result.json()["local_jobs"][0]["id"] == id
    assert result.json()["pending"][0]["prompt_id"] == "unrelated"
    assert result.json()["pending"][0]["ownership"] == "external"

def test_queue_without_jobs_still_contacts_active_runtime(client):
    id, remote = setup(client)
    with session_factory()() as db:
        job = db.get(GenerationJob, id)
        job.state, job.active_scene_id = "cancelled", None
        db.commit()
    remote.queue = {"queue_running": [], "queue_pending": [[1, "external-pending", {}, {}]]}
    from unittest.mock import patch
    with patch("frutinovelas.services.queue_control.ComfyClient", lambda *args: QueueClient(remote)):
        response = client.get("/api/v1/comfy/queue")
    assert response.status_code == 200
    body = response.json()
    assert body["server"]["available"] is True
    assert body["local_jobs"] == []
    assert body["pending"][0]["ownership"] == "external"


def test_old_runtime_mismatch_is_diagnostic_not_global_failure(client):
    id, remote = setup(client)
    with session_factory()() as db:
        job = db.get(GenerationJob, id)
        job.snapshot = {**job.snapshot, "url": "https://old-pod.example"}
        db.commit()
    remote.queue = {"queue_running": [], "queue_pending": []}
    from unittest.mock import patch
    with patch("frutinovelas.services.queue_control.ComfyClient", lambda *args: QueueClient(remote)):
        response = client.get("/api/v1/comfy/queue")
    assert response.status_code == 200
    data = response.json()
    assert data["historical_jobs"] == 1
    assert data["local_jobs"][0]["runtime"] == "historical"
    assert data["server"]["available"] is True


def test_blocked_remote_queue_returns_diagnostic_not_422(client):
    id, remote = setup(client)
    class FailedQueue(QueueClient):
        def get(self, path):
            if path == "/queue":
                raise ComfyError("HTTP unauthorized", 401)
            return super().get(path)
    from unittest.mock import patch
    with patch("frutinovelas.services.queue_control.ComfyClient", lambda *args: FailedQueue(remote)):
        response = client.get("/api/v1/comfy/queue")
    assert response.status_code == 200
    assert response.json()["server"]["code"] == "gateway_authorization"
    assert response.json()["server"]["http_status"] == 401


def test_ghost_reconciliation_refuses_live_queue_and_history(client):
    id, remote = setup(client)
    with session_factory()() as db:
        job = db.get(GenerationJob, id)
        from datetime import timedelta
        from frutinovelas.models import utcnow
        job.created_at = utcnow() - timedelta(minutes=2)
        job.state = "unknown"
        db.commit()
    remote.queue = {"queue_running": [], "queue_pending": [[1, id, {}]]}
    from unittest.mock import patch
    with patch("frutinovelas.services.queue_control.ComfyClient", lambda *args: QueueClient(remote)):
        response = client.post(f"/api/v1/generations/{id}/reconcile")
    assert response.status_code == 409
    with session_factory()() as db:
        assert db.get(GenerationJob, id).state == "unknown"
