"""Managed voices, timing validation, immutable revisions and additive migration."""

import copy
import hashlib
import io
import json
import shutil
import struct
import subprocess
import wave

import pytest
from pydantic import ValidationError

from conftest import png_bytes
from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.models import Asset
from frutinovelas.schemas import SceneAudioGuide, SceneCreate
from frutinovelas.services.assets import asset_path
from frutinovelas.services.audio import prepare_audio_path


def wav_bytes(seconds=1.0, rate=16000, channels=1, width=2):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        if width == 1:
            frame = bytes([160] + ([96] if channels == 2 else []))
        else:
            value = 8192 << (8 * (width - 2))
            frame = value.to_bytes(width, "little", signed=True)
            if channels == 2:
                frame += (-value).to_bytes(width, "little", signed=True)
        audio.writeframes(frame * round(seconds * rate))
    return output.getvalue()


def upload_audio(client, seconds=1.0, **kwargs):
    response = client.post(
        "/api/v1/assets/audio", files={"file": ("diálogo.wav", wav_bytes(seconds, **kwargs), "audio/wav")}
    )
    assert response.status_code == 201, response.text
    return response.json()


def project_chapter(client):
    project = client.post("/api/v1/projects", json={"name": "Voces"}).json()
    chapter = client.post(f"/api/v1/projects/{project['id']}/chapters", json={"title": "Capítulo"}).json()
    return project, chapter


def character(client, project, voice):
    reference = client.post(
        "/api/v1/assets", files={"file": ("persona.png", png_bytes(), "image/png")}
    ).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/characters",
        json={
            "name": "Darío", "reference_asset_id": reference["id"],
            "voice_description": "Voz grave, cálida.\nEspañol literal: «Sí».", "voice_asset_id": voice["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_pcm_is_content_validated_preserved_deduplicated_and_prepared_without_ffmpeg(client, monkeypatch, width):
    settings = get_settings()
    monkeypatch.setattr(settings, "ffmpeg_path", "not-installed-ffmpeg")
    monkeypatch.setattr(settings, "ffprobe_path", "not-installed-ffprobe")
    original = wav_bytes(channels=2, width=width)
    response = client.post(
        "/api/v1/assets/audio", files={"file": ("no-confíes-en-la-extensión.bin", original, "image/png")}
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["kind"] == "audio" and saved["mime"] == "audio/wav"
    assert saved["width"] is None and saved["height"] is None
    assert saved["duration_seconds"] == 1
    assert saved["sha256"] == hashlib.sha256(original).hexdigest()
    assert "rel_path" not in saved
    assert client.get(f"/api/v1/assets/{saved['id']}/content").content == original
    assert client.get(f"/api/v1/assets/{saved['id']}/thumb").status_code == 404
    duplicate = client.post("/api/v1/assets/audio", files={"file": ("otra.wav", original)}).json()
    assert duplicate["id"] == saved["id"]
    assert client.post("/api/v1/assets", files={"file": ("falsa.png", original)}).status_code == 422
    with session_factory()() as session:
        asset = session.get(Asset, saved["id"])
        prepared = prepare_audio_path(settings, asset)
        with wave.open(str(prepared), "rb") as audio:
            assert (audio.getframerate(), audio.getsampwidth(), audio.getnchannels()) == (32000, 2, 2)
            assert audio.getnframes() == 32000
            left, right = struct.unpack("<hh", audio.readframes(1))
            assert left > 0 and right < 0
        expected = prepared.read_bytes()
        prepared.write_bytes(expected[:-5] + b"XXXXX")
        assert prepare_audio_path(settings, asset).read_bytes() == expected
        original_path = asset_path(settings, asset)
        assert original_path.read_bytes() == original
    original_path.write_bytes(original[:-5] + b"XXXXX")
    repaired = client.post("/api/v1/assets/audio", files={"file": ("otra.wav", original)})
    assert repaired.status_code == 201, repaired.text
    assert repaired.json()["id"] == saved["id"]
    assert original_path.read_bytes() == original


@pytest.mark.parametrize("content", [b"", b"not audio", wav_bytes()[:-20], wav_bytes(0), wav_bytes(15.01)])
def test_invalid_empty_truncated_and_long_audio_is_rejected_without_leaving_files(client, content):
    response = client.post("/api/v1/assets/audio", files={"file": ("voz.wav", content, "audio/wav")})
    assert response.status_code == 422, response.text
    assert not list(get_settings().tmp_dir.glob("audio-upload-*"))
    with session_factory()() as session:
        assert session.query(Asset).count() == 0


def test_audio_upload_size_and_decoder_requirement_are_explicit(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    response = client.post("/api/v1/assets/audio", files={"file": ("voz.wav", b"x" * (1024 * 1024 + 1))})
    assert response.status_code == 422 and "1 MB" in response.json()["detail"]
    monkeypatch.setattr(settings, "ffprobe_path", "missing-ffprobe-for-test")
    response = client.post("/api/v1/assets/audio", files={"file": ("voz.mp3", b"ID3" + b"\0" * 50)})
    assert response.status_code == 422 and "FFmpeg y FFprobe" in response.json()["detail"]
    assert not list(settings.tmp_dir.glob("audio-upload-*"))


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg optional")
def test_real_compressed_audio_is_fully_decoded_and_original_preserved(client, tmp_path):
    source, compressed = tmp_path / "original.wav", tmp_path / "voice.mp3"
    source.write_bytes(wav_bytes(0.5))
    subprocess.run(
        [shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-i", str(source), "-c:a", "libmp3lame", str(compressed)],
        check=True, capture_output=True, timeout=15,
    )
    original = compressed.read_bytes()
    response = client.post("/api/v1/assets/audio", files={"file": ("voz.png", original, "image/png")})
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["mime"] == "audio/mpeg"
    assert 0.4 <= asset["duration_seconds"] <= 0.7
    assert client.get(f"/api/v1/assets/{asset['id']}/content").content == original


def test_character_voice_is_optional_preserved_for_old_put_and_enforces_asset_kinds(client):
    project, _chapter = project_chapter(client)
    voice = upload_audio(client)
    actor = character(client, project, voice)
    legacy_body = {
        "name": "Darío actualizado", "reference_asset_id": actor["reference_asset"]["id"],
        "expected_revision": actor["revision"],
    }
    response = client.put(f"/api/v1/characters/{actor['id']}", json=legacy_body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["voice_description"] == actor["voice_description"]
    assert saved["voice_asset"]["id"] == voice["id"]
    for changes in ({"reference_asset_id": voice["id"]}, {"voice_asset_id": actor["reference_asset"]["id"]}):
        rejected = client.put(
            f"/api/v1/characters/{actor['id']}",
            json={**legacy_body, "expected_revision": saved["revision"], **changes},
        )
        assert rejected.status_code == 422
    removed = client.put(
        f"/api/v1/characters/{actor['id']}",
        json={**legacy_body, "expected_revision": saved["revision"], "voice_asset_id": None, "voice_description": ""},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["voice_asset"] is None and removed.json()["voice_description"] == ""


def test_scene_audio_freezes_server_metadata_and_survives_unrelated_edits_and_duplication(client):
    project, chapter = project_chapter(client)
    voice = upload_audio(client)
    actor = character(client, project, voice)
    submitted = {
        "asset_id": voice["id"], "character_id": actor["id"], "start_seconds": 1,
        "asset": {"id": "forged", "duration_seconds": 0.001}, "character_name": "forged", "voice_description": "forged",
    }
    response = client.post(
        f"/api/v1/chapters/{chapter['id']}/scenes",
        json={"prompt": "Darío: «¡Sí, aquí!».\nNo modificar.", "parameters": {"audio_guides": [submitted]}},
    )
    assert response.status_code == 201, response.text
    scene = response.json()
    original = copy.deepcopy(scene["parameters"]["audio_guides"])
    assert scene["parameters"]["cast"] == []  # Offscreen voice need not be in the visual cast.
    assert original[0]["asset"]["id"] == voice["id"]
    assert original[0]["asset"]["duration_seconds"] == voice["duration_seconds"]
    assert original[0]["character_name"] == actor["name"]
    assert original[0]["voice_description"] == actor["voice_description"]
    another_voice = upload_audio(client, 0.5)
    edited = client.put(
        f"/api/v1/characters/{actor['id']}",
        json={
            "name": "Otra identidad", "reference_asset_id": actor["reference_asset"]["id"],
            "expected_revision": actor["revision"], "voice_description": "Voz nueva", "voice_asset_id": another_voice["id"],
        },
    )
    assert edited.status_code == 200
    altered = copy.deepcopy(scene["parameters"])
    altered["seed_mode"], altered["seed"] = "fixed", 5
    altered["audio_guides"][0]["voice_description"] = "forged again"
    saved = client.patch(
        f"/api/v1/scenes/{scene['id']}", json={"expected_revision": scene["revision"], "parameters": altered}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["parameters"]["audio_guides"] == original
    assert saved.json()["prompt"] == scene["prompt"]
    duplicate = client.post(f"/api/v1/scenes/{scene['id']}/duplicate").json()
    assert duplicate["parameters"]["audio_guides"] == original
    cleared = client.patch(
        f"/api/v1/scenes/{duplicate['id']}",
        json={"expected_revision": duplicate["revision"], "parameters": {"audio_guides": []}},
    )
    assert cleared.status_code == 200
    assert client.get(f"/api/v1/scenes/{scene['id']}").json()["parameters"]["audio_guides"] == original
    revisions = client.get(f"/api/v1/scenes/{scene['id']}/revisions").json()
    assert all(revision["parameters"]["audio_guides"] == original for revision in revisions)
    archived = client.put(
        f"/api/v1/characters/{actor['id']}",
        json={"name": "Otra identidad", "reference_asset_id": actor["reference_asset"]["id"], "expected_revision": edited.json()["revision"], "archived": True},
    )
    assert archived.status_code == 200
    moved = client.patch(
        f"/api/v1/scenes/{scene['id']}",
        json={"expected_revision": saved.json()["revision"], "parameters": {"audio_guides": [{**submitted, "start_seconds": 2}]}},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["parameters"]["audio_guides"] == [{**original[0], "start_seconds": 2}]
    fresh = client.post(
        f"/api/v1/chapters/{chapter['id']}/scenes", json={"parameters": {"audio_guides": [submitted]}}
    )
    assert fresh.status_code == 422  # An archived speaker cannot be newly attached.


def test_audio_project_scope_kind_timing_overlap_and_duration_only_edits(client):
    project, chapter = project_chapter(client)
    voice = upload_audio(client)
    actor = character(client, project, voice)
    other, other_chapter = project_chapter(client)
    assert other["id"] != project["id"]
    scoped = client.post(
        f"/api/v1/chapters/{other_chapter['id']}/scenes",
        json={"parameters": {"audio_guides": [{"asset_id": voice["id"], "character_id": actor["id"]}]}},
    )
    assert scoped.status_code == 422
    scene = client.post(f"/api/v1/chapters/{chapter['id']}/scenes", json={"duration_seconds": 5}).json()
    for guides in (
        [{"asset_id": actor["reference_asset"]["id"]}],
        [{"asset_id": voice["id"], "start_seconds": -0.01}],
        [{"asset_id": voice["id"], "start_seconds": 4.03}],  # Round to frame 97, beyond 5s with this audio.
        [{"asset_id": voice["id"], "start_seconds": 0}, {"asset_id": voice["id"], "start_seconds": 0.9}],
        [{"asset_id": voice["id"], "start_seconds": index} for index in range(9)],
    ):
        response = client.patch(
            f"/api/v1/scenes/{scene['id']}",
            json={"expected_revision": scene["revision"], "parameters": {"audio_guides": guides}},
        )
        assert response.status_code == 422, response.text
    image_rejected = client.patch(
        f"/api/v1/scenes/{scene['id']}", json={"expected_revision": scene["revision"], "start_asset_id": voice["id"]}
    )
    assert image_rejected.status_code == 422
    accepted = client.patch(
        f"/api/v1/scenes/{scene['id']}",
        json={"expected_revision": scene["revision"], "parameters": {"audio_guides": [{"asset_id": voice["id"], "start_seconds": 4.02}]}},
    )
    assert accepted.status_code == 200, accepted.text  # Round to frame 96, exactly 4s.
    shortened = client.patch(
        f"/api/v1/scenes/{scene['id']}", json={"expected_revision": accepted.json()["revision"], "duration_seconds": 4.5}
    )
    assert shortened.status_code == 422
    assert client.get(f"/api/v1/scenes/{scene['id']}").json()["duration_seconds"] == 5


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 1e308])
def test_audio_timing_and_duration_reject_nonfinite_or_unbounded_numbers(value):
    with pytest.raises(ValidationError):
        SceneAudioGuide(asset_id="a", start_seconds=value)
    with pytest.raises(ValidationError):
        SceneCreate(duration_seconds=value)


def test_audio_migration_preserves_legacy_images_voices_revisions_and_credentials(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, text

    from frutinovelas.migrate import alembic_config, upgrade_to_head

    url = "sqlite:///" + str(tmp_path / "legacy-audio.sqlite3")
    command.upgrade(alembic_config(url), "0004")
    engine = create_engine(url)
    original_parameters = json.dumps({"image_prompt": "Guion ñ\nLiteral", "cast": [{"name": "Darío"}]})
    with engine.begin() as connection:
        statements = [
            "INSERT INTO projects VALUES ('p','Proyecto','es','9:16',0,'2026-01-01','2026-01-01')",
            "INSERT INTO chapters VALUES ('c','p','Capítulo',1,'Guion ñ','Continuidad',1,0,'2026-01-01','2026-01-01')",
            "INSERT INTO assets VALUES ('a','image','assets/original.png','original-image-hash',42,'image/png',64,112,'original.png','2026-01-01')",
            "INSERT INTO characters VALUES ('actor','p','Darío','Identidad original','a',0,1,'2026-01-01','2026-01-01')",
            "INSERT INTO scenes VALUES ('s','c',1,NULL,'Escena','',1,'2026-01-01','2026-01-01')",
            "INSERT INTO comfy_connections VALUES ('default','https://example.com','preserved-ciphertext','{}','{}','2026-01-01','2026-01-01')",
        ]
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text("INSERT INTO scene_revisions VALUES ('r','s',1,'Diálogo ñ','a',NULL,5,:parameters,NULL,'ui','2026-01-01')"),
            {"parameters": original_parameters},
        )
    upgrade_to_head(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name,voice_description,voice_asset_id FROM characters")).one() == ("Darío", "", None)
        assert connection.execute(text("SELECT rel_path,duration_seconds FROM assets")).one() == ("assets/original.png", None)
        assert connection.scalar(text("SELECT parameters FROM scene_revisions")) == original_parameters
        assert connection.scalar(text("SELECT encrypted_token FROM comfy_connections")) == "preserved-ciphertext"
        assert any(row[3] == "voice_asset_id" and row[2] == "assets" for row in connection.execute(text("PRAGMA foreign_key_list(characters)")))
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005"
    engine.dispose()
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1
