import httpx

from frutinovelas.db import session_factory
from frutinovelas.models import GenerationJob, SceneRevision
from frutinovelas.services.queue_control import stop_all_jobs
from sqlalchemy import select
from test_queue_control import QueueClient, setup


def test_bulk_stop_preserves_prompts_and_is_idempotent(client):
    job_id, remote = setup(client)
    with session_factory()() as db:
        before = list(db.execute(select(SceneRevision.id, SceneRevision.prompt)))
    result = client.post("/api/v1/comfy/queue/stop-all")
    assert result.status_code == 200, result.text
    assert result.json()["cancelled"] == [job_id]
    assert result.json()["pending"] == []
    assert client.post("/api/v1/comfy/queue/stop-all").json()["cancelled"] == []
    with session_factory()() as db:
        assert list(db.execute(select(SceneRevision.id, SceneRevision.prompt))) == before
        assert db.get(GenerationJob, job_id).active_scene_id is None


def test_bulk_stop_targets_managed_pending_only(client):
    job_id, remote = setup(client)
    with session_factory()() as db:
        job = db.get(GenerationJob, job_id)
        job.state, job.prompt_id = "waiting", job_id
        db.commit()
    remote.calls = []
    remote.queue = {"queue_running": [[0, "foreign-running"]], "queue_pending": [[1, job_id], [2, "foreign-pending"]]}
    result = stop_all_jobs(client_factory=lambda *args: QueueClient(remote))
    assert result["cancelled"] == [job_id]
    assert result["pending"] == []
    assert remote.queue == {"queue_running": [[0, "foreign-running"]], "queue_pending": [[2, "foreign-pending"]]}
    assert remote.calls == [("POST", "/queue", {"delete": [job_id]})]


def test_bulk_stop_reports_unreachable_remote_without_freeing_reservation(client):
    job_id, remote = setup(client)
    with session_factory()() as db:
        db.get(GenerationJob, job_id).state = "running"
        db.commit()
    class Offline(QueueClient):
        def get(self, path):
            raise httpx.ConnectError("offline")
    result = stop_all_jobs(client_factory=lambda *args: Offline(remote))
    assert result["pending"] == [job_id]
    assert result["cancelled"] == []
    with session_factory()() as db:
        assert db.get(GenerationJob, job_id).active_scene_id is not None
