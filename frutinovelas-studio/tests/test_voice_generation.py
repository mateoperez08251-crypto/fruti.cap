"""Reusable character voices: real native graph contracts, simulated requests only."""

from __future__ import annotations

import copy
import hashlib
import json

import httpx
import pytest
from sqlalchemy import select

from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.models import Asset, GenerationJob
from frutinovelas.services.voice_workflow import (
    END_GUIDE,
    START_GUIDE,
    VOICE_UNET,
    VOICE_UNET_SHA256,
    VOICE_WORKFLOW,
    VoiceWorkflowError,
    derive_voice_workflow,
    effective_voice_prompt,
    prepare_voice_graph,
    validate_voice_node_info,
    validate_voice_references,
)
from test_audio_generation import AudioRemote, native_node_info, native_workflow, run_tick, wav_bytes
from test_generation import FILENAME, TOKEN, connect, scene, submit


def voice_base_workflow():
    """Complete conditioning/loader links needed by the shared kit derivation."""
    graph = native_workflow()
    graph["5"]["inputs"]["unet_name"] = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    graph.update({
        "6": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax"}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_int8_convrot.safetensors"}},
        "29": {"class_type": "ComfyMathExpression", "inputs": {"expression": "max(5, round(a*24)) + (5-max(5, round(a*24)) % 17) % 17", "values.a": ["28", 0]}},
    })
    graph["9"]["inputs"].update({"clip": ["6", 0], "vae": ["7", 0], "length": ["29", 0]})
    return graph


def voice_node_info():
    """Pinned V3 schema: dynamic sockets are advertised as autogrow templates."""
    info = native_node_info()

    def autogrow(prefix, kind, count):
        return ["COMFY_AUTOGROW_V3", {"template": {"input": {"required": {prefix.rstrip("_"): [kind, {}]}}, "prefix": prefix, "min": 0, "max": count}}]

    info["MiniMaxH3ReferenceToVideo"] = {
        "input": {
            "required": {
                "clip": ["CLIP"], "prompt": ["STRING"], "width": ["INT"], "height": ["INT"], "length": ["INT"],
                "ref_image_size": ["COMBO", {"options": ["match", "max"]}],
            },
            "optional": {
                "vae": ["VAE"], "audio_vae": ["VAE"],
                "ref_images": autogrow("ref_image_", "IMAGE", 9),
                "ref_audios": autogrow("ref_audio_", "AUDIO", 3),
                "ref_videos": autogrow("ref_video_", "IMAGE", 3),
                "ref_video_audios": autogrow("ref_video_audio_", "AUDIO", 3),
            },
        },
        "output": ["CONDITIONING", "LATENT"],
    }
    return info


def voice_reference(asset_id="voice-one", name="Darío", duration=2.0):
    return {
        "character_id": "character-" + asset_id, "character_name": name,
        "voice_description": "Voz cálida y pausada", "asset_id": asset_id,
        "asset": {"id": asset_id, "kind": "audio", "sha256": "a" * 64, "duration_seconds": duration},
    }


class VoiceRemote(AudioRemote):
    def __init__(self):
        super().__init__()
        self.raw = json.dumps(voice_base_workflow()).encode()
        self.voice_raw = json.dumps(derive_voice_workflow(voice_base_workflow(), VOICE_UNET)).encode()
        self.identity["workflows"].update({
            FILENAME: hashlib.sha256(self.raw).hexdigest(),
            VOICE_WORKFLOW: hashlib.sha256(self.voice_raw).hexdigest(),
        })
        self.identity["modelos"]["h3_diffusion_ref2va_pruned_int8"] = {"archivo": VOICE_UNET, "sha256": VOICE_UNET_SHA256}
        self.object_info = voice_node_info()
        self.on_voice_fetch = None

    def handle(self, request):
        if request.url.path == "/frutinovelas/workflows/" + VOICE_WORKFLOW:
            assert request.headers.get("authorization") == "Bearer " + TOKEN
            self.calls.append((request.method, request.url.path))
            if self.on_voice_fetch:
                self.on_voice_fetch()
            return httpx.Response(200, content=self.voice_raw)
        return super().handle(request)


@pytest.fixture
def voice_remote(monkeypatch):
    remote = VoiceRemote()
    monkeypatch.setattr("frutinovelas.routes.generation.ComfyClient", remote.client)
    monkeypatch.setattr("frutinovelas.services.generation.ComfyClient", remote.client)
    return remote


def save_scene_voices(client, original, *, seconds=(2.0,), names=("Darío",)):
    chapter = client.get("/api/v1/chapters/" + original["chapter_id"]).json()
    characters, assets = [], []
    for index, (duration, name) in enumerate(zip(seconds, names, strict=True)):
        response = client.post("/api/v1/assets/audio", files={"file": ("muestra.wav", wav_bytes(duration, level=1200 + index), "audio/wav")})
        assert response.status_code == 201, response.text
        asset = response.json()
        response = client.post(
            f"/api/v1/projects/{chapter['project_id']}/characters",
            json={"name": name, "reference_asset_id": original["start_asset"]["id"], "voice_asset_id": asset["id"], "voice_description": "Voz cálida y pausada"},
        )
        assert response.status_code == 201, response.text
        characters.append(response.json())
        assets.append(asset)
    response = client.patch(
        "/api/v1/scenes/" + original["id"],
        json={"expected_revision": original["revision"], "parameters": {"voice_character_ids": [character["id"] for character in characters]}},
    )
    assert response.status_code == 200, response.text
    return response.json(), assets, characters


def test_kit_derivation_uses_ref2va_with_native_visual_anchors_and_no_sample_placeholders():
    base = voice_base_workflow()
    unchanged = copy.deepcopy(base)
    graph = derive_voice_workflow(base, VOICE_UNET)
    assert base == unchanged
    assert graph["5"]["inputs"]["unet_name"] == VOICE_UNET
    assert graph["9"]["class_type"] == "MiniMaxH3ReferenceToVideo"
    assert graph["9"]["inputs"]["audio_vae"] == ["8", 0]
    assert graph["9"]["inputs"]["ref_images.ref_image_0"] == ["1", 0]
    assert graph["9"]["inputs"]["ref_images.ref_image_1"] == ["30", 0]
    assert "first_frame" not in graph["9"]["inputs"] and "last_frame" not in graph["9"]["inputs"]
    assert graph[START_GUIDE]["inputs"] == {"positive": ["9", 0], "latent": ["9", 1], "vae": ["7", 0], "image": ["1", 0], "frame_idx": 0}
    assert graph[END_GUIDE]["inputs"]["positive"] == [START_GUIDE, 0]
    assert graph[END_GUIDE]["inputs"]["image"] == ["30", 0] and graph[END_GUIDE]["inputs"]["frame_idx"] == -1
    assert graph["15"]["inputs"]["conditioning"] == [END_GUIDE, 0]
    assert all(node["class_type"] != "LoadAudio" for node in graph.values())
    assert not any(key.startswith("ref_audios") for key in graph["9"]["inputs"])
    for node_id in ("6", "7", "8", "12", "14", "16", "18", "19", "20", "28", "29"):
        assert graph[node_id] == base[node_id]


@pytest.mark.parametrize("with_end", [True, False])
def test_three_voice_samples_are_context_not_timed_soundtrack(with_end):
    graph = derive_voice_workflow(voice_base_workflow(), VOICE_UNET)
    unchanged = copy.deepcopy(graph)
    references = [voice_reference(str(index), name, 5) for index, name in enumerate(("Darío", "Bruno", "Celia"))]
    result = prepare_voice_graph(graph, "new dialogue", 4, 31, "start.png", "end.png" if with_end else None, "job", references, ["one.wav", "two.wav", "three.wav"])
    assert graph == unchanged
    for index, name in enumerate(("one.wav", "two.wav", "three.wav")):
        assert result[f"fruti_voice_audio_{index}"]["inputs"] == {"audio": name}
        assert result["9"]["inputs"][f"ref_audios.ref_audio_{index}"] == [f"fruti_voice_audio_{index}", 0]
    assert result["28"]["inputs"]["value"] == 4  # five-second samples need not fit this four-second scene
    assert result["16"] == graph["16"] and result["18"] == graph["18"] and result["19"] == graph["19"]
    for node in result.values():
        if node["class_type"] == "MiniMaxH3AddGuide":
            assert "image" in node["inputs"] and "audio" not in node["inputs"]
    if with_end:
        assert result["15"]["inputs"]["conditioning"] == [END_GUIDE, 0]
    else:
        assert "30" not in result and END_GUIDE not in result
        assert "ref_images.ref_image_1" not in result["9"]["inputs"]
        assert result["15"]["inputs"]["conditioning"] == [START_GUIDE, 0]


def test_ref2va_prompt_preserves_dialogue_and_speaker_order_while_binding_voice_timbre():
    dialogue = "Darío (S2) says <d>[Spanish] ¿Dónde estás?\nsummary: aquí.</d>\nBruno (S1) replies <d>[Spanish] Para ahí.</d>"
    original = "integrated_multimodal_description:\n" + dialogue + "\noverall_soundscape: viento\nnon_diegetic_music: N/A."
    refs = [voice_reference(), voice_reference("two", "Bruno")]
    effective = effective_voice_prompt(original, refs, end_frame=True)
    assert dialogue in effective
    assert '<Audio 1> is the voice-timbre reference for the character named "Darío" (S2).' in effective
    assert '<Audio 2> is the voice-timbre reference for the character named "Bruno" (S1).' in effective
    assert "integrated_multimodal_description:" not in effective
    assert "detailed_description:" in effective and "End on <Picture 2>." in effective
    assert "new dialogue" in effective and "keep that voice offscreen and preserve the visible cast" in effective
    assert "overall_soundscape:\nviento" in effective
    retention = effective.split("retention_analysis:\n", 1)[1].split("detailed_description:", 1)[0]
    assert "(S1)" not in retention and "(S2)" not in retention
    assert effective_voice_prompt(original, []) == original
    with pytest.raises(VoiceWorkflowError, match="etiquetas"):
        effective_voice_prompt("Use <Audio 1> as the complete original soundtrack", refs)


@pytest.mark.parametrize("change", ["audio_vae", "prefix", "max", "min", "audio_type", "image_type", "output", "extra_required", "not_object", "no_match"])
def test_preflight_checks_real_v3_audio_and_image_input_contract(change):
    info = voice_node_info()
    validate_voice_node_info(info)
    node = info["MiniMaxH3ReferenceToVideo"]
    template = node["input"]["optional"]["ref_audios"][1]["template"]
    if change == "audio_vae":
        del node["input"]["optional"]["audio_vae"]
    elif change in ("prefix", "max", "min"):
        template[change] = {"prefix": "different_", "max": 2, "min": 1}[change]
    elif change == "audio_type":
        template["input"]["required"]["ref_audio"] = ["IMAGE"]
    elif change == "image_type":
        node["input"]["optional"]["ref_images"][1]["template"]["input"]["required"]["ref_image"] = ["AUDIO"]
    elif change == "output":
        node["output"] = ["LATENT", "CONDITIONING"]
    elif change == "extra_required":
        node["input"]["required"]["unexpected"] = ["STRING"]
    elif change == "not_object":
        info = []
    else:
        node["input"]["required"]["ref_image_size"] = ["COMBO", {"options": ["max"]}]
    with pytest.raises(VoiceWorkflowError, match="MiniMaxH3ReferenceToVideo"):
        validate_voice_node_info(info)


@pytest.mark.parametrize("refs", [
    [voice_reference(duration=1.9)], [voice_reference(duration=15.1)], [voice_reference(duration=float("nan"))],
    [voice_reference(), voice_reference()], [voice_reference(str(i)) for i in range(4)],
    [voice_reference("one", duration=8), voice_reference("two", duration=8)],
])
def test_invalid_frozen_voice_samples_cannot_prepare_a_job(refs):
    with pytest.raises(VoiceWorkflowError):
        validate_voice_references(refs)


def test_frozen_voice_and_new_dialogue_reach_native_conditioning_after_library_and_scene_edits(client, voice_remote):
    connect(client)
    saved, assets, characters = save_scene_voices(client, scene(client), seconds=(10.0,))
    response = submit(client, saved)
    assert response.status_code == 202, response.text
    job = response.json()
    assert TOKEN not in response.text and "snapshot" not in job
    with session_factory()() as db:
        stored = db.get(GenerationJob, job["id"])
        snapshot = copy.deepcopy(stored.snapshot)
        assert stored.encrypted_token != TOKEN
    assert snapshot["workflow"] == VOICE_WORKFLOW
    assert snapshot["voice_references"] == saved["parameters"]["voice_references"]
    assert snapshot["prompt"] == saved["prompt"] and snapshot["effective_prompt"] != snapshot["prompt"]
    character = characters[0]
    changed = client.put(
        "/api/v1/characters/" + character["id"],
        json={"expected_revision": character["revision"], "name": "Otra identidad", "voice_description": "Otra voz", "voice_asset_id": None, "reference_asset_id": character["reference_asset"]["id"]},
    )
    assert changed.status_code == 200, changed.text
    changed = client.patch(
        "/api/v1/scenes/" + saved["id"],
        json={"expected_revision": saved["revision"], "prompt": "Texto nuevo", "parameters": {"voice_character_ids": []}},
    )
    assert changed.status_code == 200, changed.text
    assert submit(client, saved, job["id"]).json()["id"] == job["id"]
    run_tick(voice_remote)
    sent = voice_remote.posts[0]["prompt"]
    assert sent["9"]["inputs"]["prompt"] == snapshot["effective_prompt"]
    assert "Otra identidad" not in sent["9"]["inputs"]["prompt"]
    assert sent["9"]["inputs"]["ref_audios.ref_audio_0"] == ["fruti_voice_audio_0", 0]
    assert sent["fruti_voice_audio_0"]["inputs"]["audio"] == "audio/voice-1.wav"
    assert b"RIFF" in voice_remote.audio_uploads[0] and b"WAVE" in voice_remote.audio_uploads[0]
    assert len(voice_remote.posts) == 1 and len(voice_remote.audio_uploads) == 1
    assert voice_remote.calls.count(("GET", "/frutinovelas/workflows/" + VOICE_WORKFLOW)) == 1
    assert voice_remote.calls.index(("GET", "/object_info/MiniMaxH3ReferenceToVideo")) < voice_remote.calls.index(("POST", "/upload/image"))
    with session_factory()() as db:
        assert db.get(GenerationJob, job["id"]).snapshot == snapshot
    assert client.get("/api/v1/assets/" + assets[0]["id"] + "/content").content == wav_bytes(10.0)


def test_one_saved_sample_can_generate_different_dialogue_in_multiple_scenes(client, voice_remote):
    connect(client)
    saved, assets, characters = save_scene_voices(client, scene(client, end=False))
    voice_remote.done = True
    first = submit(client, saved)
    assert first.status_code == 202, first.text
    run_tick(voice_remote)
    response = client.post(
        f"/api/v1/chapters/{saved['chapter_id']}/scenes",
        json={"title": "Otro diálogo", "start_asset_id": saved["start_asset"]["id"], "prompt": "Darío (S1) says <d>[Spanish] Mañana volvemos.</d>", "duration_seconds": 5, "parameters": {"voice_character_ids": [characters[0]["id"]]}},
    )
    assert response.status_code == 201, response.text
    other = response.json()
    assert other["parameters"]["voice_references"][0]["asset_id"] == assets[0]["id"]
    second = submit(client, other)
    assert second.status_code == 202, second.text
    run_tick(voice_remote)
    assert len(voice_remote.posts) == 2
    assert "Mañana volvemos." not in voice_remote.posts[0]["prompt"]["9"]["inputs"]["prompt"]
    assert "Mañana volvemos." in voice_remote.posts[1]["prompt"]["9"]["inputs"]["prompt"]
    assert client.get("/api/v1/generations/" + second.json()["id"]).json()["state"] == "completed"
    with session_factory()() as db:
        assert len(db.scalars(select(Asset).where(Asset.kind == "audio")).all()) == 1


@pytest.mark.parametrize("problem", ["missing", "hash", "weights", "graph", "identity", "network"])
def test_unverified_voice_workflow_is_rejected_before_enqueue_or_upload(client, voice_remote, problem):
    if problem == "missing":
        del voice_remote.identity["workflows"][VOICE_WORKFLOW]
    elif problem == "hash":
        voice_remote.voice_raw += b" "
    elif problem == "weights":
        voice_remote.identity["modelos"]["h3_diffusion_ref2va_pruned_int8"]["sha256"] = "0" * 64
    elif problem == "graph":
        voice_remote.voice_raw = b"[]"
        voice_remote.identity["workflows"][VOICE_WORKFLOW] = hashlib.sha256(voice_remote.voice_raw).hexdigest()
    connect(client)
    saved, _, _ = save_scene_voices(client, scene(client))
    if problem == "identity":
        voice_remote.identity["session_id"] = "another-runtime"
    elif problem == "network":
        def fail():
            raise httpx.ReadTimeout("private transport detail")
        voice_remote.on_voice_fetch = fail
    response = submit(client, saved)
    assert response.status_code == 422, response.text
    assert TOKEN not in response.text and "private transport detail" not in response.text
    assert not voice_remote.posts and not voice_remote.uploads
    with session_factory()() as db:
        assert db.scalar(select(GenerationJob.id)) is None


def test_scene_revision_is_rechecked_after_remote_voice_workflow_read(client, voice_remote):
    connect(client)
    saved, _, _ = save_scene_voices(client, scene(client))

    def edit_scene():
        response = client.patch("/api/v1/scenes/" + saved["id"], json={"expected_revision": saved["revision"], "prompt": "Changed while checking the remote graph"})
        assert response.status_code == 200, response.text

    voice_remote.on_voice_fetch = edit_scene
    response = submit(client, saved)
    assert response.status_code == 409, response.text
    with session_factory()() as db:
        assert db.scalar(select(GenerationJob.id)) is None
    assert not voice_remote.uploads and not voice_remote.posts


def test_unsupported_native_voice_node_fails_once_before_upload_or_gpu(client, voice_remote):
    connect(client)
    saved, _, _ = save_scene_voices(client, scene(client))
    job = submit(client, saved).json()
    del voice_remote.object_info["MiniMaxH3ReferenceToVideo"]
    run_tick(voice_remote)
    status = client.get("/api/v1/generations/" + job["id"]).json()
    assert status["state"] == "failed" and "MiniMaxH3ReferenceToVideo" in status["error"]
    run_tick(voice_remote)
    assert not voice_remote.uploads and not voice_remote.posts


@pytest.mark.parametrize("tamper", ["file", "duration"])
def test_tampered_voice_sample_is_rejected_before_any_upload(client, voice_remote, tamper):
    connect(client)
    saved, assets, _ = save_scene_voices(client, scene(client))
    job = submit(client, saved).json()
    with session_factory()() as db:
        asset = db.get(Asset, assets[0]["id"])
        path = get_settings().resolved_data_dir / asset.rel_path
        if tamper == "duration":
            asset.duration_seconds = 3.0
            db.commit()
    if tamper == "file":
        path.write_bytes(wav_bytes(2, level=2400))
    run_tick(voice_remote)
    status = client.get("/api/v1/generations/" + job["id"]).json()
    assert status["state"] == "failed" and "cambió" in status["error"]
    assert not voice_remote.uploads and not voice_remote.posts


def test_uncertain_ref2va_submission_recovers_without_resubmitting_or_uploading_again(client, voice_remote):
    connect(client)
    saved, _, _ = save_scene_voices(client, scene(client))
    job = submit(client, saved).json()
    voice_remote.lose_response = True
    run_tick(voice_remote)
    assert client.get("/api/v1/generations/" + job["id"]).json()["state"] == "unknown"
    voice_remote.done = True
    run_tick(voice_remote)
    assert client.get("/api/v1/generations/" + job["id"]).json()["state"] == "completed"
    assert len(voice_remote.posts) == 1 and len(voice_remote.audio_uploads) == 1


def test_no_selected_voices_keeps_fl2va_without_loading_optional_model_or_workflow(client, voice_remote):
    del voice_remote.identity["workflows"][VOICE_WORKFLOW]
    voice_remote.identity["modelos"] = {}
    voice_remote.object_info = {}
    connect(client)
    original = scene(client, end=False)
    response = submit(client, original)
    assert response.status_code == 202, response.text
    run_tick(voice_remote)
    sent = voice_remote.posts[0]["prompt"]
    assert sent["9"]["class_type"] == "MiniMaxH3ImageToVideo"
    assert sent["9"]["inputs"]["prompt"] == original["prompt"]
    assert sent["5"]["inputs"]["unet_name"] == "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    assert not voice_remote.audio_uploads
    assert not any(path.endswith(VOICE_WORKFLOW) or path.startswith("/object_info/") for _, path in voice_remote.calls)
