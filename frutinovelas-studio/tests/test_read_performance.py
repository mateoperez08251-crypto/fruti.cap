"""Read paths must not grow with old prompts, workflows or per-chapter round trips."""

from collections import Counter
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import Session

from frutinovelas.db import get_engine, session_factory
from frutinovelas.models import Asset, Chapter, GenerationJob, Project, Scene, SceneRevision


@contextmanager
def reads():
    loaded = Counter()
    statements = []

    def on_load(_session, instance):
        loaded[type(instance)] += 1

    def on_sql(_conn, _cursor, statement, _params, _ctx, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(Session, "loaded_as_persistent", on_load)
    event.listen(get_engine(), "before_cursor_execute", on_sql)
    try:
        yield loaded, statements
    finally:
        event.remove(Session, "loaded_as_persistent", on_load)
        event.remove(get_engine(), "before_cursor_execute", on_sql)


def seed():
    with session_factory()() as session:
        project = Project(name="Large project")
        chapters = [Chapter(title=f"Chapter {i}", order_index=i) for i in range(6)]
        project.chapters = chapters
        project.chapters.append(Chapter(title="Archived", archived=True))
        empty = Project(name="Empty")
        session.add_all([project, empty])
        asset = Asset(rel_path="unused.png", sha256="a" * 64, size_bytes=10, mime="image/png")
        session.add(asset)
        session.flush()
        for chapter in chapters:
            for index in range(4):
                scene = Scene(chapter_id=chapter.id, title=f"Scene {index}", order_index=index)
                for number in range(1, 21):
                    scene.revisions.append(
                        SceneRevision(
                            number=number,
                            prompt="historical " * 1000,
                            duration_seconds=5,
                            start_asset_id=asset.id,
                        )
                    )
                scene.revisions[-1].prompt = (
                    "Current literal ñ\n<d>Hola</d>" if index < 3 else "\t\n\u3000\xa0"
                )
                if index == 2:
                    scene.revisions[-1].start_asset_id = None
                session.add(scene)
            session.add(Scene(chapter_id=chapter.id, title="No revision", order_index=4))
        session.commit()
        return project.id, chapters[0].id, empty.id


def test_scene_list_reads_only_latest_revisions_and_preserves_history(client):
    _project, chapter, _empty = seed()
    with reads() as (loaded, statements):
        response = client.get(f"/api/v1/chapters/{chapter}/scenes")
    assert response.status_code == 200
    scenes = response.json()
    assert loaded[SceneRevision] == 4  # 80 saved revisions, only four are current.
    assert len(statements) == 2  # Chapter existence + one joined read.
    assert [s["status"] for s in scenes] == ["lista", "lista", "sin_imagen", "sin_prompt", "sin_imagen"]
    assert scenes[0]["revision_number"] == 20
    assert scenes[0]["prompt"] == "Current literal ñ\n<d>Hola</d>"
    assert scenes[2]["start_asset"] is None
    history = client.get(f"/api/v1/scenes/{scenes[0]['id']}/revisions").json()
    assert len(history) == 20
    assert history[-1]["prompt"] == "historical " * 1000


def test_chapter_counts_do_not_materialize_scenes_or_revisions(client):
    project, chapter, empty = seed()
    with reads() as (loaded, statements):
        chapters = client.get(f"/api/v1/projects/{project}/chapters").json()
    assert len(statements) == 2  # Independent of the number of chapters.
    assert loaded[Scene] == loaded[SceneRevision] == loaded[Asset] == 0
    assert len(chapters) == 6
    assert all(c["scene_count"] == 5 and c["ready_count"] == 2 for c in chapters)
    assert client.get(f"/api/v1/chapters/{chapter}").json()["ready_count"] == 2
    assert client.get(f"/api/v1/projects/{empty}/chapters").json() == []
    with reads() as (_loaded, statements):
        projects = client.get("/api/v1/projects").json()
    assert len(statements) == 1
    counts = {p["id"]: p["chapter_count"] for p in projects}
    assert counts[project] == 6 and counts[empty] == 0


def test_progress_reads_summaries_without_loading_scene_history_or_job_snapshots(client):
    _project, chapter, _empty = seed()
    scene = client.get(f"/api/v1/chapters/{chapter}/scenes").json()[0]
    ids = []
    with session_factory()() as session:
        for i in range(8):
            job = GenerationJob(
                scene_id=scene["id"],
                state="completed",
                prompt_id=f"prompt-{i}",
                snapshot={
                    "duration": 5.5,
                    "revision_number": 20,
                    "seed": 9007199254740991,
                    "prompt": "old prompt" * 1000,
                    "graph": {"large": "x" * 100_000},
                },
                encrypted_token="must-not-be-loaded",
                result_path=f"versions/{i}.mp4",
            )
            session.add(job)
            session.flush()
            ids.append(job.id)
        session.commit()
    expected = [client.get(f"/api/v1/generations/{id}").json() for id in reversed(ids)]
    with reads() as (loaded, statements):
        response = client.get(f"/api/v1/scenes/{scene['id']}/generations")
    assert response.json() == expected
    assert len(statements) == 2
    assert loaded[SceneRevision] == loaded[GenerationJob] == loaded[Scene] == 0
    assert "generation_jobs.encrypted_token" not in statements[-1]
    assert "JSON_EXTRACT" in statements[-1]
    assert client.get("/api/v1/scenes/missing/generations").status_code == 404
