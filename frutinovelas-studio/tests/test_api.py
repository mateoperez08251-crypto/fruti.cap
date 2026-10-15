"""Pruebas de la API v1 (fase 1): datos persistentes, revisiones, conflictos y archivos."""

from __future__ import annotations

# pyrefly: ignore [missing-import]
from conftest import png_bytes
from fastapi.testclient import TestClient

from frutinovelas.config import reset_settings_cache
from frutinovelas.db import reset_engine_cache

PROMPT = 'Wide shot. <d>Darío: "¡Mira el mar!"</d>\n\nLínea 2 con ñ y emoji 🍐\n'


def _upload(client, data=None, name="inicio.png"):
    r = client.post("/api/v1/assets", files={"file": (name, data or png_bytes(), "image/png")})
    assert r.status_code == 201, r.text
    return r.json()


def _chapter(client):
    p = client.post("/api/v1/projects", json={"name": "FRUTINOVELAS"}).json()
    c = client.post(f"/api/v1/projects/{p['id']}/chapters", json={"title": "Capítulo 1"}).json()
    return p, c


def test_health_and_status(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"
    s = client.get("/api/v1/system/status").json()
    assert "comfyui" in s and "storage" in s


def test_full_flow_persists_after_restart(client, data_dir):
    p, c = _chapter(client)
    start = _upload(client)
    end = _upload(client, png_bytes((10, 90, 30)), "final.png")
    r = client.post(
        f"/api/v1/chapters/{c['id']}/scenes",
        json={"title": "Viaje", "prompt": PROMPT, "duration_seconds": 3, "start_asset_id": start["id"], "end_asset_id": end["id"]},
    )
    assert r.status_code == 201, r.text
    scene = r.json()
    assert scene["mode"] == "FL2VA"
    assert scene["status"] == "lista"
    assert scene["prompt"] == PROMPT  # literal, sin recortes

    # Reinicio: nueva app sobre el mismo directorio de datos.
    reset_settings_cache()
    reset_engine_cache()
    from frutinovelas.api import create_app

    with TestClient(create_app()) as c2:
        got = c2.get(f"/api/v1/scenes/{scene['id']}").json()
        assert got["prompt"] == PROMPT
        assert got["end_asset"]["id"] == end["id"]
        assert c2.get(f"/api/v1/assets/{start['id']}/content").status_code == 200


def test_edit_creates_revision_and_conflict_returns_409(client):
    _, c = _chapter(client)
    s = client.post(f"/api/v1/chapters/{c['id']}/scenes", json={"prompt": "uno"}).json()
    assert s["revision_number"] == 1

    r = client.patch(f"/api/v1/scenes/{s['id']}", json={"expected_revision": s["revision"], "prompt": "dos"})
    assert r.status_code == 200
    s2 = r.json()
    assert s2["revision_number"] == 2

    # Mismo expected_revision antiguo: conflicto, sin sobrescribir.
    r = client.patch(f"/api/v1/scenes/{s['id']}", json={"expected_revision": s["revision"], "prompt": "tres"})
    assert r.status_code == 409
    assert client.get(f"/api/v1/scenes/{s['id']}").json()["prompt"] == "dos"

    # El título no crea revisión de contenido.
    r = client.patch(f"/api/v1/scenes/{s['id']}", json={"expected_revision": s2["revision"], "title": "Nuevo"})
    assert r.json()["revision_number"] == 2

    revs = client.get(f"/api/v1/scenes/{s['id']}/revisions").json()
    assert [x["prompt"] for x in revs] == ["dos", "uno"]


def test_remove_end_image_switches_to_i2va(client):
    _, c = _chapter(client)
    a, b = _upload(client), _upload(client, png_bytes((1, 2, 3)))
    s = client.post(
        f"/api/v1/chapters/{c['id']}/scenes", json={"start_asset_id": a["id"], "end_asset_id": b["id"]}
    ).json()
    r = client.patch(f"/api/v1/scenes/{s['id']}", json={"expected_revision": s["revision"], "end_asset_id": None})
    assert r.json()["mode"] == "I2VA"


def test_end_without_start_is_rejected(client):
    _, c = _chapter(client)
    b = _upload(client)
    r = client.post(f"/api/v1/chapters/{c['id']}/scenes", json={"end_asset_id": b["id"]})
    assert r.status_code == 422


def test_reorder_keeps_ids(client):
    _, c = _chapter(client)
    ids = [client.post(f"/api/v1/chapters/{c['id']}/scenes", json={}).json()["id"] for _ in range(3)]
    new = [ids[2], ids[0], ids[1]]
    r = client.put(f"/api/v1/chapters/{c['id']}/scene-order", json={"scene_ids": new})
    assert [s["id"] for s in r.json()] == new
    bad = client.put(f"/api/v1/chapters/{c['id']}/scene-order", json={"scene_ids": ids[:2]})
    assert bad.status_code == 422


def test_duplicate_inserts_after(client):
    _, c = _chapter(client)
    a = client.post(f"/api/v1/chapters/{c['id']}/scenes", json={"prompt": "A"}).json()
    b = client.post(f"/api/v1/chapters/{c['id']}/scenes", json={"prompt": "B"}).json()
    client.post(f"/api/v1/scenes/{a['id']}/duplicate")
    order = [s["prompt"] for s in client.get(f"/api/v1/chapters/{c['id']}/scenes").json()]
    assert order == ["A", "A", "B"]
    assert b["id"] in [s["id"] for s in client.get(f"/api/v1/chapters/{c['id']}/scenes").json()]


def test_upload_rejects_fake_image_and_dedupes(client):
    r = client.post("/api/v1/assets", files={"file": ("x.png", b"esto no es una imagen", "image/png")})
    assert r.status_code == 422
    one, two = _upload(client), _upload(client)
    assert one["id"] == two["id"]
    assert client.get(f"/api/v1/assets/{one['id']}/thumb?size=128").status_code == 200


def test_chapter_conflict(client):
    _, c = _chapter(client)
    ok = client.patch(f"/api/v1/chapters/{c['id']}", json={"expected_revision": c["revision"], "script_md": "# Guion"})
    assert ok.status_code == 200
    stale = client.patch(f"/api/v1/chapters/{c['id']}", json={"expected_revision": c["revision"], "script_md": "x"})
    assert stale.status_code == 409


def test_token_required_for_writes(data_dir, monkeypatch):
    monkeypatch.setenv("FRUTINOVELAS_API_TOKEN", "abc")
    reset_settings_cache()
    from frutinovelas.api import create_app

    with TestClient(create_app()) as c:
        assert c.post("/api/v1/projects", json={"name": "x"}).status_code == 401
        assert c.get("/api/v1/projects").status_code == 200
        ok = c.post("/api/v1/projects", json={"name": "x"}, headers={"Authorization": "Bearer abc"})
        assert ok.status_code == 201
