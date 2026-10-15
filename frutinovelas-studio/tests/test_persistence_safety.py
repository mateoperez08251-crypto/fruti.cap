"""Regresiones de conflictos reales entre peticiones simultáneas."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select

from frutinovelas.db import session_factory
from frutinovelas.models import AuditEvent, GenerationJob
from frutinovelas.services.generation import ACTIVE


@pytest.mark.parametrize(
    "entity,field", [("chapters", "script_md"), ("scenes", "title"), ("scenes", "prompt")]
)
def test_concurrent_updates_preserve_winner_and_return_conflict(client, monkeypatch, entity, field):
    project = client.post("/api/v1/projects", json={"name": "Concurrencia"}).json()
    chapter = client.post(f"/api/v1/projects/{project['id']}/chapters", json={"title": "Capítulo"}).json()
    barrier = Barrier(2, timeout=10)

    if entity == "chapters":
        from frutinovelas.routes import projects as routes

        original = routes._chapter_or_404
        loader_name = "_chapter_or_404"
        record = chapter
    else:
        from frutinovelas.routes import scenes as routes

        original = routes._scene
        loader_name = "_scene"
        record = client.post(f"/api/v1/chapters/{chapter['id']}/scenes", json={"prompt": "original"}).json()

    def load_both_before_writing(*args, **kwargs):
        loaded = original(*args, **kwargs)
        barrier.wait()
        return loaded

    path = f"/api/v1/{entity}/{record['id']}"

    with monkeypatch.context() as patch:
        patch.setattr(routes, loader_name, load_both_before_writing)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(client.patch, path, json={"expected_revision": record["revision"], field: value})
                for value in ("primero", "segundo")
            ]
            responses = [future.result(timeout=15) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json() for response in responses if response.status_code == 200)
    persisted = client.get(path).json()
    assert persisted[field] == winner[field]
    assert persisted["revision"] == record["revision"] + 1
    if field == "prompt":
        revisions = client.get(path + "/revisions").json()
        assert [revision["prompt"] for revision in revisions] == [winner[field], "original"]


@pytest.mark.parametrize("state", ACTIVE)
def test_cannot_delete_scene_or_parent_while_generation_is_active(client, state):
    project = client.post("/api/v1/projects", json={"name": "Generación"}).json()
    chapter = client.post(f"/api/v1/projects/{project['id']}/chapters", json={"title": "Capítulo"}).json()
    scene = client.post(f"/api/v1/chapters/{chapter['id']}/scenes", json={"prompt": "Conservar"}).json()
    with session_factory()() as db:
        job = GenerationJob(
            scene_id=scene["id"],
            active_scene_id=scene["id"],
            state=state,
            prompt_id=str(uuid4()),
            snapshot={},
            encrypted_token="test",
        )
        db.add(job)
        db.commit()
        job_id = job.id

    assert client.delete(f"/api/v1/scenes/{scene['id']}").status_code == 409
    assert client.delete(f"/api/v1/chapters/{chapter['id']}").status_code == 409
    # Projects deliberately expose archiving, not a cascading delete endpoint.
    assert client.delete(f"/api/v1/projects/{project['id']}").status_code == 405
    assert client.get(f"/api/v1/scenes/{scene['id']}").json()["prompt"] == "Conservar"
    with session_factory()() as db:
        assert db.get(GenerationJob, job_id).state == state
        assert db.scalar(select(AuditEvent).where(AuditEvent.event == "scene.deleted")) is None


@pytest.mark.parametrize("state", ["completed", "failed"])
def test_finished_generation_does_not_prevent_explicit_scene_deletion(client, state):
    project = client.post("/api/v1/projects", json={"name": "Terminado"}).json()
    chapter = client.post(f"/api/v1/projects/{project['id']}/chapters", json={"title": "Capítulo"}).json()
    scene = client.post(f"/api/v1/chapters/{chapter['id']}/scenes", json={}).json()
    with session_factory()() as db:
        db.add(
            GenerationJob(
                scene_id=scene["id"], state=state, prompt_id=str(uuid4()), snapshot={}, encrypted_token="test"
            )
        )
        db.commit()

    assert client.delete(f"/api/v1/scenes/{scene['id']}").status_code == 204
    assert client.get(f"/api/v1/scenes/{scene['id']}").status_code == 404
    assert client.delete(f"/api/v1/chapters/{chapter['id']}").status_code == 204


def test_reordering_does_not_invalidate_saved_content_revision(client):
    project = client.post("/api/v1/projects", json={"name": "Orden"}).json()
    chapter = client.post(f"/api/v1/projects/{project['id']}/chapters", json={"title": "Capítulo"}).json()
    scenes = [client.post(f"/api/v1/chapters/{chapter['id']}/scenes", json={}).json() for _ in range(2)]
    response = client.put(
        f"/api/v1/chapters/{chapter['id']}/scene-order",
        json={"scene_ids": [scene["id"] for scene in reversed(scenes)]},
    )
    assert response.status_code == 200
    for scene in scenes:
        edited = client.patch(
            f"/api/v1/scenes/{scene['id']}",
            json={"expected_revision": scene["revision"], "prompt": "Actualizado"},
        )
        assert edited.status_code == 200
