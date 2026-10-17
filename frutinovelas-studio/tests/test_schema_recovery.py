"""Real SQLite recovery, including a stamped/partially applied legacy revision."""

import json
import sqlite3
from contextlib import closing

import pytest
from alembic import command
from fastapi.testclient import TestClient

from conftest import png_bytes
from frutinovelas.api import create_app
from frutinovelas.config import get_settings
from frutinovelas.migrate import alembic_config, upgrade_to_head

SNAPSHOT = json.dumps(
    {"prompt": "Diálogo ñ\nBruno, espera.", "seed": 17, "duration": 5, "revision_number": 1}
)


def legacy_database(stamp="0003", missing=("kind", "result_asset_id")):
    path = get_settings().db_path
    url = "sqlite:///" + str(path)
    command.upgrade(alembic_config(url), "0003")
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("INSERT INTO projects VALUES ('p','Mi proyecto','es','9:16',0,'2026-01-01','2026-01-01')")
        db.execute(
            "INSERT INTO chapters VALUES ('c','p','Capítulo',1,'Guion ñ','Luz cálida',1,0,'2026-01-01','2026-01-01')"
        )
        db.execute("INSERT INTO scenes VALUES ('s','c',1,NULL,'Auto','',1,'2026-01-01','2026-01-01')")
        db.execute(
            "INSERT INTO assets VALUES ('a','image','assets/old.png','old-hash',1,'image/png',64,112,'original.png','2026-01-01')"
        )
        db.execute(
            "INSERT INTO characters VALUES ('actor','p','Darío','Pera detective','a',0,1,'2026-01-01','2026-01-01')"
        )
        db.execute(
            "INSERT INTO comfy_connections VALUES ('default','https://example.com','preserve-encrypted-token','{}','{}','2026-01-01','2026-01-01')"
        )
        db.execute(
            "INSERT INTO generation_jobs (id,scene_id,state,prompt_id,snapshot,encrypted_token,error,created_at,updated_at) VALUES ('j','s','completed','pid',?,'job-private-token','','2026-01-01','2026-01-01')",
            (SNAPSHOT,),
        )
        for name in missing:
            assert name in ("kind", "result_asset_id")
            db.execute(f"ALTER TABLE generation_jobs DROP COLUMN {name}")
        db.execute("UPDATE alembic_version SET version_num=?", (stamp,))
        db.commit()
    return path, url


@pytest.mark.parametrize("stamp", ["0002", "0003"])
@pytest.mark.parametrize("missing", [("kind",), ("result_asset_id",), ("kind", "result_asset_id")])
def test_recovery_preserves_projects_characters_jobs_and_credentials(data_dir, stamp, missing):
    path, url = legacy_database(stamp, missing)
    upgrade_to_head(url)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute(
            "SELECT kind,result_asset_id,snapshot,encrypted_token FROM generation_jobs"
        ).fetchone() == ("video", None, SNAPSHOT, "job-private-token")
        assert db.execute("SELECT name FROM characters").fetchone() == ("Darío",)
        assert db.execute("SELECT script_md,continuity_md FROM chapters").fetchone() == (
            "Guion ñ",
            "Luz cálida",
        )
        assert db.execute("SELECT encrypted_token FROM comfy_connections").fetchone() == (
            "preserve-encrypted-token",
        )
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0005",)
        assert db.execute("PRAGMA quick_check").fetchone() == ("ok",)
    backups = list((data_dir / "backups").glob("*.sqlite3"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        before = {row[1] for row in backup.execute("PRAGMA table_info(generation_jobs)")}
        assert all(name not in before for name in missing)
        assert backup.execute("SELECT snapshot FROM generation_jobs").fetchone() == (SNAPSHOT,)
        assert backup.execute("SELECT version_num FROM alembic_version").fetchone() == (stamp,)
    upgrade_to_head(url)
    assert list((data_dir / "backups").glob("*.sqlite3")) == backups


def test_legacy_stamp_without_new_tables_is_repaired(data_dir):
    path = get_settings().db_path
    url = "sqlite:///" + str(path)
    command.upgrade(alembic_config(url), "0002")
    with closing(sqlite3.connect(path)) as db:
        db.execute("UPDATE alembic_version SET version_num='0003'")
        db.commit()
    upgrade_to_head(url)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT COUNT(*) FROM characters").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM chapter_renders").fetchone() == (0,)
        assert "kind" in {row[1] for row in db.execute("PRAGMA table_info(generation_jobs)")}


def test_api_starts_on_legacy_db_and_can_add_second_character(data_dir):
    legacy_database()
    with TestClient(create_app()) as client:
        old = client.get("/api/v1/projects/p/characters")
        assert old.status_code == 200 and old.json()[0]["name"] == "Darío"
        upload = client.post("/api/v1/assets", files={"file": ("Bruno.png", png_bytes(), "image/png")})
        assert upload.status_code == 201
        response = client.post(
            "/api/v1/projects/p/characters",
            json={"name": "Bruno", "description": "Aguacate", "reference_asset_id": upload.json()["id"]},
        )
        assert response.status_code == 201, response.text
        assert {c["name"] for c in client.get("/api/v1/projects/p/characters").json()} == {"Darío", "Bruno"}
        assert client.get("/api/v1/scenes/s/image-generations").status_code == 200


def test_inconsistent_current_schema_stops_before_worker(data_dir, monkeypatch):
    path = get_settings().db_path
    upgrade_to_head()
    with closing(sqlite3.connect(path)) as db:
        db.execute("ALTER TABLE generation_jobs DROP COLUMN kind")
        db.commit()

    def unexpected_start(_self):
        pytest.fail("A worker must not start against an incomplete schema")

    monkeypatch.setattr("frutinovelas.worker.GenerationWorker.start", unexpected_start)
    monkeypatch.setattr(
        "frutinovelas.api.get_settings", lambda: get_settings().model_copy(update={"embedded_worker": True})
    )
    with pytest.raises(RuntimeError, match="generation_jobs.kind"):
        with TestClient(create_app()):
            pass
