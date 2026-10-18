"""Crear capítulos completos mediante MCP, sin invocar GPU ni duplicar escenas."""
import pytest


def _proxy(client):
    def call(method, path, body=None, raw=False):
        r = client.request(method, "/api/v1/" + path, json=body)
        r.raise_for_status()
        return r.content if raw else r.json()
    return call


def _plan(project_id, char_id):
    return {
        "project_id": project_id,
        "plan_id": "cap2-detectives",
        "chapter_title": "Capítulo 2 — La última visita",
        "script_md": "# Prueba de capítulo 2\nEl equipo llega al lugar.",
        "continuity_md": "No cambiar la identidad de los personajes.",
        "scenes": [
            {
                "title": "Llegada",
                "description": "Llegan al perímetro.",
                "image_prompt": "Portrait 9:16 cinematic frutinovela, approved character, carefully staged on a city street.",
                "animation_prompt": "integrated_multimodal_description:\nThe detective stops before the perimeter.\noverall_soundscape:\nWind.\nnon_diegetic_music:\nN/A",
                "duration_seconds": 6,
                "character_ids": [char_id],
                "voice_character_ids": [],
            },
            {
                "title": "La pregunta",
                "description": "Hablan del caso.",
                "image_prompt": "Portrait 9:16 cinematic frutinovela, approved detective near secured crime scene entrance.",
                "animation_prompt": "integrated_multimodal_description:\nThe detective asks one careful question.\noverall_soundscape:\nWind.\nnon_diegetic_music:\nN/A",
                "duration_seconds": 7,
                "character_ids": [char_id],
            },
        ],
    }


@pytest.mark.asyncio
async def test_full_chapter_creation_and_idempotent_retry_preserve_old_chapters(client, monkeypatch):
    from conftest import png_bytes
    from frutinovelas import mcp_studio
    from frutinovelas.mcp_server import create_server

    project = client.post("/api/v1/projects", json={"name": "Detectives"}).json()
    previous = client.post(f"/api/v1/projects/{project['id']}/chapters", json={"title": "Capítulo 1", "script_md": "Original"}).json()
    image = client.post("/api/v1/assets", files={"file": ("detective.png", png_bytes(), "image/png")}).json()
    character = client.post(f"/api/v1/projects/{project['id']}/characters", json={
        "name": "Detective", "reference_asset_id": image["id"],
    }).json()

    monkeypatch.setattr(mcp_studio, "studio_request", _proxy(client))
    mcp = create_server()
    plan = _plan(project["id"], character["id"])
    result = await mcp.call_tool("create_studio_chapter_plan", {"plan": plan})
    assert not result.is_error, result
    chapters = client.get(f"/api/v1/projects/{project['id']}/chapters").json()
    assert [c["title"] for c in chapters] == ["Capítulo 1", "Capítulo 2 — La última visita"]
    assert client.get(f"/api/v1/chapters/{previous['id']}").json()["script_md"] == "Original"
    scenes = client.get(f"/api/v1/chapters/{chapters[1]['id']}/scenes").json()
    assert len(scenes) == 2
    assert [s["duration_seconds"] for s in scenes] == [6, 7]
    assert scenes[0]["parameters"]["character_ids"] == [character["id"]]
    assert all(s["parameters"]["image_approval"] == "manual" for s in scenes)
    assert all(s["parameters"]["image_prompt"] and s["prompt"] for s in scenes)
    assert all(s["status"] == "sin_imagen" for s in scenes)

    retry = await mcp.call_tool("create_studio_chapter_plan", {"plan": plan})
    assert not retry.is_error, retry
    assert len(client.get(f"/api/v1/projects/{project['id']}/chapters").json()) == 2
    after = client.get(f"/api/v1/chapters/{chapters[1]['id']}/scenes").json()
    assert [s["id"] for s in after] == [s["id"] for s in scenes]
    assert [s["revision"] for s in after] == [s["revision"] for s in scenes]


@pytest.mark.asyncio
async def test_refuses_invalid_reference_before_creating_chapter(client, monkeypatch):
    from frutinovelas import mcp_studio
    from frutinovelas.mcp_server import create_server

    project = client.post("/api/v1/projects", json={"name": "Detectives"}).json()
    monkeypatch.setattr(mcp_studio, "studio_request", _proxy(client))
    plan = _plan(project["id"], "missing-character")
    mcp = create_server()
    result = await mcp.call_tool("create_studio_chapter_plan", {"plan": plan})
    assert result.is_error
    assert client.get(f"/api/v1/projects/{project['id']}/chapters").json() == []


@pytest.mark.asyncio
async def test_refuses_to_overwrite_changed_scene(client, monkeypatch):
    from conftest import png_bytes
    from frutinovelas import mcp_studio
    from frutinovelas.mcp_server import create_server

    project = client.post("/api/v1/projects", json={"name": "Detectives"}).json()
    image = client.post("/api/v1/assets", files={"file": ("detective.png", png_bytes(), "image/png")}).json()
    character = client.post(f"/api/v1/projects/{project['id']}/characters", json={
        "name": "Detective", "reference_asset_id": image["id"],
    }).json()
    monkeypatch.setattr(mcp_studio, "studio_request", _proxy(client))
    plan = _plan(project["id"], character["id"])
    mcp = create_server()
    result = await mcp.call_tool("create_studio_chapter_plan", {"plan": plan})
    assert not result.is_error
    chapter = client.get(f"/api/v1/projects/{project['id']}/chapters").json()[0]
    scene = client.get(f"/api/v1/chapters/{chapter['id']}/scenes").json()[0]
    assert client.patch(f"/api/v1/scenes/{scene['id']}", json={
        "expected_revision": scene["revision"], "prompt": "Editado manualmente.",
    }).status_code == 200
    result = await mcp.call_tool("create_studio_chapter_plan", {"plan": plan})
    assert result.is_error
    assert len(client.get(f"/api/v1/chapters/{chapter['id']}/scenes").json()) == 2
    after = client.get(f"/api/v1/scenes/{scene['id']}").json()
    assert after["prompt"] == "Editado manualmente."
