"""Disconnected runtimes, uncertain delivery, preservation and race regressions."""
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.models import ChapterRender, GenerationJob, utcnow
from frutinovelas.services.generation import ACTIVE
from frutinovelas.services.queue_control import stop_job
from frutinovelas.services.queue_recovery import recover_available
from frutinovelas.worker import GenerationWorker, WorkerLock
from test_generation import URL, Remote, connect, scene, submit
from test_queue_control import QueueClient, setup


@pytest.fixture
def remote(monkeypatch):
    instance = Remote()
    monkeypatch.setattr("frutinovelas.routes.generation.ComfyClient", instance.client)
    return instance


def age_job(job_id, state, historical=False):
    with session_factory()() as db:
        job = db.get(GenerationJob, job_id)
        job.state = state
        job.updated_at = utcnow() - timedelta(minutes=2)
        if historical:
            job.snapshot = {**job.snapshot, "url": "https://dead-colab.example"}
        db.commit()


def stored(job_id):
    with session_factory()() as db:
        job = db.get(GenerationJob, job_id)
        db.expunge(job)
        return job


@pytest.mark.parametrize("state", ACTIVE)
def test_historical_jobs_release_without_contacting_dead_url_or_remote_mutations(client, state):
    job_id, remote = setup(client)
    age_job(job_id, state, historical=True)
    original = stored(job_id)
    remote.queue = {"queue_running": [[0, "someone-else"]], "queue_pending": [[1, "another"]]}
    remote.calls = []

    def factory(url, token):
        assert url == URL
        return QueueClient(remote)

    assert recover_available(client_factory=factory)["recovered"] == [job_id]
    assert recover_available(client_factory=factory)["recovered"] == []
    job = stored(job_id)
    assert job.state == "cancelled" and job.active_scene_id is None
    assert job.snapshot == original.snapshot
    assert remote.calls == []
    assert remote.queue["queue_running"] == [[0, "someone-else"]]


@pytest.mark.parametrize("state", ["waiting", "running", "unknown", "submitting", "downloading"])
def test_absent_current_jobs_release_without_replay(client, state):
    job_id, remote = setup(client)
    age_job(job_id, state)
    remote.queue = {"queue_running": [], "queue_pending": []}
    assert recover_available(client_factory=lambda *args: QueueClient(remote))["recovered"] == [job_id]


@pytest.mark.parametrize("location", ["queue_running", "queue_pending", "history"])
def test_real_remote_work_or_results_preserve_reservation(client, location):
    job_id, remote = setup(client)
    age_job(job_id, "unknown")
    remote.queue = {"queue_running": [], "queue_pending": []}
    if location != "history":
        remote.queue[location] = [[0, job_id]]

    class Live(QueueClient):
        def get(self, path):
            if path.startswith("/history/") and location == "history":
                return {job_id: {"status": {"completed": True}}}
            return super().get(path)

    assert recover_available(client_factory=lambda *args: Live(remote))["recovered"] == []
    assert stored(job_id).active_scene_id is not None


@pytest.mark.parametrize("broken", ["timeout", "partial", "history", "identity"])
def test_unverifiable_remote_is_never_proof_of_absence(client, broken):
    job_id, remote = setup(client)
    age_job(job_id, "unknown")
    remote.queue = {"queue_running": [], "queue_pending": []}

    class Broken(QueueClient):
        def get(self, path):
            if broken == "timeout":
                raise httpx.ReadTimeout("offline")
            if broken == "partial" and path == "/queue":
                return {"queue_running": []}
            if broken == "history" and path.startswith("/history/"):
                return []
            if broken == "identity" and path == "/frutinovelas/identity":
                return {"session_id": "different"}
            return super().get(path)

    assert recover_available(client_factory=lambda *args: Broken(remote))["recovered"] == []
    assert stored(job_id).active_scene_id is not None


def test_recent_submission_and_real_local_queue_are_not_orphans(client):
    job_id, remote = setup(client)
    remote.queue = {"queue_running": [], "queue_pending": []}
    for state in ("queued", "uploading", "submitting"):
        with session_factory()() as db:
            job = db.get(GenerationJob, job_id)
            job.state, job.updated_at = state, utcnow()
            db.commit()
        assert recover_available(client_factory=lambda *args: QueueClient(remote))["recovered"] == []


def test_result_appearing_between_history_and_queue_is_preserved(client):
    job_id, remote = setup(client)
    age_job(job_id, "unknown")
    remote.queue = {"queue_running": [], "queue_pending": []}

    class Finishing(QueueClient):
        histories = 0
        def get(self, path):
            if path.startswith("/history/"):
                self.histories += 1
                return {} if self.histories == 1 else {job_id: {"status": {"completed": True}}}
            return super().get(path)

    assert recover_available(client_factory=lambda *args: Finishing(remote))["recovered"] == []
    assert stored(job_id).state == "unknown"


def test_recovery_excludes_inflight_worker(client):
    job_id, _ = setup(client)
    age_job(job_id, "uploading", historical=True)
    lock = WorkerLock(get_settings().resolved_data_dir / "generation_worker.lock")
    assert lock.acquire()
    try:
        assert recover_available()["status"] == "busy"
        assert stored(job_id).state == "uploading"
    finally:
        lock.release()


def test_cancel_during_upload_prevents_post_and_keeps_sources(client, remote, monkeypatch):
    connect(client)
    s = scene(client)
    job_id = submit(client, s).json()["id"]
    original_client = remote.client

    def factory(url, token):
        instance = original_client(url, token)
        upload = instance.upload
        def cancel_then_upload(path):
            stop_job(job_id)
            return upload(path)
        instance.upload = cancel_then_upload
        return instance

    worker = GenerationWorker(client_factory=factory)
    worker.tick()
    assert remote.posts == []
    assert stored(job_id).state == "cancelled"
    assert client.get(f"/api/v1/scenes/{s['id']}").json() == s


def test_worker_recovers_old_head_and_dispatches_legitimate_next_job(client, remote):
    connect(client)
    old = submit(client, scene(client)).json()["id"]
    age_job(old, "queued", historical=True)
    # Insert next request while the recovery lock is held, as during normal dispatch.
    lock = WorkerLock(get_settings().resolved_data_dir / "generation_worker.lock")
    assert lock.acquire()
    try:
        next_job = submit(client, scene(client)).json()["id"]
    finally:
        lock.release()
    GenerationWorker(client_factory=remote.client).tick()
    assert stored(old).state == "cancelled"
    assert len(remote.posts) == 1
    assert remote.posts[0]["client_id"] == "frutinovelas-" + next_job


def test_twenty_literal_scene_prompts_and_assets_survive_recovery(client):
    job_id, remote = setup(client)
    s = client.get("/api/v1/scenes/" + stored(job_id).scene_id).json()
    chapter_id = s["chapter_id"]
    for index in range(19):
        result = client.post(f"/api/v1/chapters/{chapter_id}/scenes", json={
            "title": f"Irena Sendler — {index + 2}",
            "prompt": f"Literal «Niños a salvo», escena {index + 2}\nSin cambiar tildes.",
            "parameters": {"image_prompt": f"Ecos del Pasado, imagen {index + 2}"},
            "start_asset_id": s["start_asset"]["id"], "duration_seconds": 5,
        })
        assert result.status_code == 201
    before = client.get(f"/api/v1/chapters/{chapter_id}/scenes").json()
    age_job(job_id, "running", historical=True)
    with session_factory()() as db:
        db.add(ChapterRender(id=str(uuid4()), chapter_id=chapter_id, active_chapter_id=chapter_id,
                             state="generating", snapshot={"scenes": [{"image_job_id": job_id}]}))
        db.commit()
    remote.queue = {"queue_running": [], "queue_pending": []}
    recover_available(client_factory=lambda *args: QueueClient(remote))
    after = client.get(f"/api/v1/chapters/{chapter_id}/scenes").json()
    assert len(after) == 20 and after == before
    from sqlalchemy import select
    with session_factory()() as db:
        run = db.scalar(select(ChapterRender))
        assert run.state == "failed" and run.active_chapter_id is None


def test_changed_tunnel_preserves_real_job_and_updates_transport_only(client):
    job_id, remote = setup(client)
    age_job(job_id, "running", historical=True)
    original = stored(job_id)
    remote.queue = {"queue_running": [[0, job_id]], "queue_pending": []}
    result = recover_available(client_factory=lambda *args: QueueClient(remote))
    assert result["recovered"] == []
    job = stored(job_id)
    assert job.state == "running" and job.active_scene_id is not None
    assert job.snapshot == {**original.snapshot, "url": URL}


def test_connection_change_during_recovery_prevents_stale_update(client):
    from frutinovelas.models import ComfyConnection
    job_id, remote = setup(client)
    age_job(job_id, "unknown")
    remote.queue = {"queue_running": [], "queue_pending": []}
    class Changing(QueueClient):
        def get(self, path):
            if path.startswith("/history/"):
                with session_factory()() as db:
                    db.get(ComfyConnection, "default").url = "https://new.example"
                    db.commit()
            return super().get(path)
    assert recover_available(client_factory=lambda *args: Changing(remote))["recovered"] == []
    assert stored(job_id).active_scene_id is not None


def test_unknown_server_never_receives_global_interrupt(client):
    from frutinovelas.services.comfy import ComfyError
    job_id, remote = setup(client)
    age_job(job_id, "running")
    remote.queue = {"queue_running": [[0, job_id]], "queue_pending": []}
    remote.calls = []
    with pytest.raises(ComfyError, match="interrupción por ID"):
        stop_job(job_id, client_factory=lambda *args: QueueClient(remote))
    assert remote.calls == []


def test_stop_requested_does_not_discard_a_completed_remote_result(client, remote):
    connect(client)
    job_id = submit(client, scene(client)).json()["id"]
    worker = GenerationWorker(client_factory=remote.client)
    worker.tick()
    with session_factory()() as db:
        job = db.get(GenerationJob, job_id)
        job.snapshot = {**job.snapshot, "stop_requested": True}
        db.commit()
    remote.done = True
    worker.tick()
    job = stored(job_id)
    assert job.state == "completed"
    assert job.result_path and job.result_sha256
    assert len(remote.posts) == 1
