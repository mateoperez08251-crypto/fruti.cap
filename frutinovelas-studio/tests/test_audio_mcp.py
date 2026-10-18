"""Exercise audio selection through the MCP tool and the actual Studio API."""

import io
import wave

import pytest


def dialogue_wav(seconds=1):
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * (8000 * seconds))
    return out.getvalue()


@pytest.mark.asyncio
async def test_mcp_saves_preserves_and_explicitly_clears_audio_guides(client, monkeypatch):
    from frutinovelas import mcp_studio
    from frutinovelas.mcp_server import create_server

    project = client.post("/api/v1/projects", json={"name": "Voces MCP"}).json()
    chapter = client.post(
        f"/api/v1/projects/{project['id']}/chapters", json={"title": "Capítulo"}
    ).json()
    literal = "integrated_multimodal_description:\nEl diálogo literal: ¿Dónde estás?\n"
    scene = client.post(
        f"/api/v1/chapters/{chapter['id']}/scenes",
        json={"prompt": literal, "duration_seconds": 5},
    ).json()
    uploaded = client.post(
        "/api/v1/assets/audio", files={"file": ("dialogo.wav", dialogue_wav(), "audio/wav")}
    )
    assert uploaded.status_code == 201
    asset = uploaded.json()
    calls = []

    def proxy(method, path, body=None, raw=False):
        calls.append((method, path))
        response = (
            client.request(method, "/api/v1/" + path, json=body)
            if body is not None
            else client.request(method, "/api/v1/" + path)
        )
        response.raise_for_status()
        return response.content if raw else response.json()

    monkeypatch.setattr(mcp_studio, "studio_request", proxy)
    server = create_server()
    result = await server.call_tool(
        "save_scene_preparation",
        {
            "scene_id": scene["id"],
            "expected_revision": scene["revision"],
            "audio_guides": [
                {"asset_id": asset["id"], "character_id": None, "start_seconds": 1.0}
            ],
        },
    )
    assert not result.is_error
    saved = client.get(f"/api/v1/scenes/{scene['id']}").json()
    original_guides = saved["parameters"]["audio_guides"]
    assert saved["prompt"] == literal
    assert original_guides[0]["asset_id"] == asset["id"]
    assert original_guides[0]["asset"]["duration_seconds"] == pytest.approx(1.0)

    result = await server.call_tool(
        "save_scene_preparation",
        {
            "scene_id": scene["id"],
            "expected_revision": saved["revision"],
            "animation_prompt": literal + "Otra línea.",
            "image_prompt": "Keep the approved characters.",
        },
    )
    assert not result.is_error
    saved = client.get(f"/api/v1/scenes/{scene['id']}").json()
    assert saved["parameters"]["audio_guides"] == original_guides
    assert saved["prompt"] == literal + "Otra línea."

    result = await server.call_tool(
        "save_scene_preparation",
        {
            "scene_id": scene["id"],
            "expected_revision": saved["revision"],
            "audio_guides": [],
        },
    )
    assert not result.is_error
    cleared = client.get(f"/api/v1/scenes/{scene['id']}").json()
    assert cleared["parameters"]["audio_guides"] == []
    assert cleared["parameters"]["image_prompt"] == "Keep the approved characters."
    assert all(method in {"GET", "PATCH"} for method, _ in calls)


@pytest.mark.asyncio
async def test_mcp_selects_reusable_voice_and_preserves_it_when_only_dialogue_changes(client, monkeypatch):
    from conftest import png_bytes
    from frutinovelas import mcp_studio
    from frutinovelas.mcp_server import create_server

    project = client.post("/api/v1/projects", json={"name": "Voces nuevas MCP"}).json()
    chapter = client.post(
        f"/api/v1/projects/{project['id']}/chapters", json={"title": "Capítulo"}
    ).json()
    scene = client.post(
        f"/api/v1/chapters/{chapter['id']}/scenes",
        json={"prompt": "Darío (S1) says <d>[Spanish] ¿Dónde estás?</d>", "duration_seconds": 5},
    ).json()
    image = client.post(
        "/api/v1/assets", files={"file": ("dario.png", png_bytes(), "image/png")}
    )
    assert image.status_code == 201, image.text
    sample = client.post(
        "/api/v1/assets/audio", files={"file": ("muestra.wav", dialogue_wav(3), "audio/wav")}
    )
    assert sample.status_code == 201, sample.text
    character = client.post(
        f"/api/v1/projects/{project['id']}/characters",
        json={"name": "Darío", "reference_asset_id": image.json()["id"],
              "voice_asset_id": sample.json()["id"], "voice_description": "Grave y cálida"},
    )
    assert character.status_code == 201, character.text
    character_id = character.json()["id"]
    calls = []

    def proxy(method, path, body=None, raw=False):
        calls.append((method, path))
        response = (
            client.request(method, "/api/v1/" + path, json=body)
            if body is not None else client.request(method, "/api/v1/" + path)
        )
        response.raise_for_status()
        return response.content if raw else response.json()

    monkeypatch.setattr(mcp_studio, "studio_request", proxy)
    server = create_server()
    result = await server.call_tool("save_scene_preparation", {
        "scene_id": scene["id"], "expected_revision": scene["revision"],
        "voice_character_ids": [character_id],
    })
    assert not result.is_error
    saved = client.get(f"/api/v1/scenes/{scene['id']}").json()
    references = saved["parameters"]["voice_references"]
    assert references[0]["character_name"] == "Darío"
    assert references[0]["asset_id"] == sample.json()["id"]
    assert saved["parameters"].get("audio_guides", []) == []

    new_dialogue = "Darío (S1) says <d>[Spanish] ¡Ya te encontré!</d>"
    result = await server.call_tool("save_scene_preparation", {
        "scene_id": scene["id"], "expected_revision": saved["revision"],
        "animation_prompt": new_dialogue,
    })
    assert not result.is_error
    saved = client.get(f"/api/v1/scenes/{scene['id']}").json()
    assert saved["prompt"] == new_dialogue
    assert saved["parameters"]["voice_references"] == references

    result = await server.call_tool("save_scene_preparation", {
        "scene_id": scene["id"], "expected_revision": saved["revision"],
        "voice_character_ids": [],
    })
    assert not result.is_error
    cleared = client.get(f"/api/v1/scenes/{scene['id']}").json()
    assert cleared["parameters"]["voice_character_ids"] == []
    assert cleared["parameters"]["voice_references"] == []
    assert all(method in {"GET", "PATCH"} for method, _ in calls)
