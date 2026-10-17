"""Native H3 audio integration; all remote responses are simulated, without GPU."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import struct
import wave

import httpx
import pytest

from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.models import Asset, GenerationJob
from frutinovelas.services.audio_workflow import (
    AudioWorkflowError,
    effective_audio_prompt,
    validate_audio_guides,
    validate_audio_node_info,
)
from frutinovelas.services.comfy import prepare_graph
from frutinovelas.worker import GenerationWorker
from test_generation import FILENAME, TOKEN, Remote, connect, scene, submit, workflow


def native_workflow():
    graph = workflow()
    graph.update(
        {
            "8": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
            "15": {"class_type": "BasicGuider", "inputs": {"conditioning": ["9", 0], "model": ["5", 0]}},
            "16": {"class_type": "SamplerCustomAdvanced", "inputs": {"latent_image": ["9", 1], "guider": ["15", 0]}},
            "18": {"class_type": "VAEDecodeAudio", "inputs": {"vae": ["8", 0], "samples": ["16", 0]}},
            "19": {"class_type": "CreateVideo", "inputs": {"images": ["17", 0], "audio": ["18", 0], "fps": 24}},
        }
    )
    return graph


def native_node_info():
    # Field names/types are from the pinned ComfyUI 0.40.0 source. LoadAudio's
    # empty combo is valid before this job's file has been uploaded.
    return {
        "LoadAudio": {"input": {"required": {"audio": [[], {"audio_upload": True}]}}, "output": ["AUDIO"]},
        "MiniMaxH3AddGuide": {
            "input": {
                "required": {"positive": ["CONDITIONING"], "latent": ["LATENT"], "frame_idx": ["INT"]},
                "optional": {"audio_vae": ["VAE"], "audio": ["AUDIO"], "vae": ["VAE"], "image": ["IMAGE"]},
            },
            "output": ["CONDITIONING"],
        },
    }


def guide(asset_id="voice-one", name="Darío", start=0.0, duration=1.0):
    return {
        "asset_id": asset_id,
        "character_id": "character-" + asset_id if name else None,
        "start_seconds": start,
        "asset": {"id": asset_id, "kind": "audio", "sha256": "a" * 64, "duration_seconds": duration},
        "character_name": name,
        "voice_description": "Voz cálida y pausada" if name else "",
    }


def wav_bytes(seconds=1.0, level=1200):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(32000)
        stream.writeframes(struct.pack("<h", level) * round(seconds * 32000))
    return buffer.getvalue()


class AudioRemote(Remote):
    def __init__(self):
        super().__init__()
        self.raw = json.dumps(native_workflow()).encode()
        self.identity["workflows"][FILENAME] = hashlib.sha256(self.raw).hexdigest()
        self.object_info = native_node_info()
        self.calls = []
        self.audio_uploads = []

    def handle(self, request):
        assert request.headers.get("authorization") == "Bearer " + TOKEN
        self.calls.append((request.method, request.url.path))
        if request.url.path.startswith("/object_info/"):
            name = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={name: self.object_info[name]} if name in self.object_info else {})
        if request.url.path == "/upload/image" and b"Content-Type: audio/wav" in request.content:
            self.audio_uploads.append(request.content)
            self.uploads.append(request.content)
            return httpx.Response(200, json={"name": f"voice-{len(self.audio_uploads)}.wav", "subfolder": "audio"})
        return super().handle(request)


@pytest.fixture
def audio_remote(monkeypatch):
    remote = AudioRemote()
    monkeypatch.setattr("frutinovelas.routes.generation.ComfyClient", remote.client)
    return remote


def save_scene_audio(client, original_scene, *, start=0.0, with_character=True, level=1200):
    response = client.post(
        "/api/v1/assets/audio", files={"file": ("diálogo.wav", wav_bytes(level=level), "audio/wav")}
    )
    assert response.status_code == 201, response.text
    asset = response.json()
    character = None
    if with_character:
        chapter = client.get(f"/api/v1/chapters/{original_scene['chapter_id']}").json()
        response = client.post(
            f"/api/v1/projects/{chapter['project_id']}/characters",
            json={
                "name": "Darío", "reference_asset_id": original_scene["start_asset"]["id"],
                "voice_description": "Voz cálida y pausada", "voice_asset_id": asset["id"],
            },
        )
        assert response.status_code == 201, response.text
        character = response.json()
    response = client.patch(
        "/api/v1/scenes/" + original_scene["id"],
        json={
            "expected_revision": original_scene["revision"],
            "parameters": {
                "audio_guides": [{"asset_id": asset["id"], "character_id": character["id"] if character else None, "start_seconds": start}]
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json(), asset, character


def run_tick(remote):
    worker = GenerationWorker(client_factory=remote.client)
    try:
        worker.tick()
    finally:
        worker.stop()


def test_audio_guides_extend_the_real_h3_conditioning_and_keep_native_output():
    original = native_workflow()
    unchanged = copy.deepcopy(original)
    guides = [guide(start=0.02), guide("voice-two", "Bruno", start=2.03)]
    prompt = effective_audio_prompt("Diálogo literal con tildes: «¿Dónde estás?»", guides)
    sent = prepare_graph(
        original, prompt, 5, 9, "first.png", "last.png", "job-one",
        audio_guides=guides, audio_names=["one.wav", "two.wav"],
    )
    assert original == unchanged
    assert sent["fruti_audio_0"]["inputs"] == {"audio": "one.wav"}
    assert sent["fruti_guide_0"]["inputs"] == {
        "positive": ["9", 0], "latent": ["9", 1], "audio_vae": ["8", 0],
        "audio": ["fruti_audio_0", 0], "frame_idx": 0,
    }
    assert sent["fruti_guide_1"]["inputs"]["positive"] == ["fruti_guide_0", 0]
    assert sent["fruti_guide_1"]["inputs"]["frame_idx"] == 49
    assert sent["15"]["inputs"]["conditioning"] == ["fruti_guide_1", 0]
    assert sent["16"] == original["16"]  # the sampler still receives H3's AV latent
    assert sent["18"] == original["18"] and sent["19"] == original["19"]
    assert sent["5"] == original["5"] and sent["14"] == original["14"]
    assert sent["9"]["inputs"]["prompt"] == prompt
    assert not any("ref_audio" in key for key in sent["9"]["inputs"])
    reordered = prepare_graph(
        original, prompt, 5, 9, "first.png", "last.png", "job-one",
        audio_guides=list(reversed(guides)), audio_names=["two.wav", "one.wav"],
    )
    assert reordered == sent  # names remain paired with their original guide
    with pytest.raises(AudioWorkflowError, match="Falta subir"):
        prepare_graph(original, prompt, 5, 9, "first.png", None, "job", audio_guides=guides, audio_names=["one.wav"])


def test_effective_prompt_retains_dialogue_fields_and_existing_speaker_ids():
    literal = (
        "integrated_multimodal_description:\n(S2) Darío says <d>[Spanish] ¿Dónde estás?</d>\n"
        "overall_soundscape: viento\nnon_diegetic_music: N/A."
    )
    result = effective_audio_prompt(literal, [guide(start=0.5)])
    assert literal.split("overall_soundscape")[0] in result
    assert result.endswith("overall_soundscape: viento\nnon_diegetic_music: N/A.")
    assert '(S2) Darío says <d>[Spanish] ¿Dónde estás?</d>' in result
    assert '0.500-1.500s, the character named "Darío"' in result
    assert "Voz cálida y pausada" in result
    assert "If this character is already visible" in result
    assert "keep the voice offscreen and preserve the visible cast" in result
    assert result.index("Audio guide timing") < result.index("overall_soundscape")
    assert "<Audio" not in result and "(S1)" not in result
    assert effective_audio_prompt(literal, []) == literal


@pytest.mark.parametrize(
    "guides,duration",
    [([guide(start=-1)], 5), ([guide(start=float("nan"))], 5), ([guide(start=4.1)], 5),
     ([guide(), guide("two", start=0.5)], 5), ([guide()] * 9, 15)],
)
def test_invalid_frozen_audio_timing_never_becomes_a_graph(guides, duration):
    with pytest.raises(AudioWorkflowError):
        validate_audio_guides(guides, duration)


@pytest.mark.parametrize("field", ["missing", "type", "extra_required", "output", "not_object"])
def test_node_schema_must_have_the_real_audio_contract(field):
    info = native_node_info()
    for class_type in info:
        validate_audio_node_info(class_type, info)
    node = info["MiniMaxH3AddGuide"]
    if field == "missing":
        del node["input"]["optional"]["audio_vae"]
    elif field == "type":
        node["input"]["optional"]["audio"] = ["IMAGE"]
    elif field == "extra_required":
        node["input"]["required"]["unsupported"] = ["STRING"]
    elif field == "not_object":
        info = []
    else:
        node["output"] = None
    with pytest.raises(AudioWorkflowError, match="MiniMaxH3AddGuide"):
        validate_audio_node_info("MiniMaxH3AddGuide", info)


def test_audio_waveform_upload_and_frozen_speaker_reach_the_submitted_graph(client, audio_remote):
    connect(client)
    saved, asset, character = save_scene_audio(client, scene(client), start=0.5)
    job = submit(client, saved).json()
    with session_factory()() as db:
        snapshot = copy.deepcopy(db.get(GenerationJob, job["id"]).snapshot)
    assert snapshot["prompt"] == saved["prompt"]
    assert snapshot["audio_guides"] == saved["parameters"]["audio_guides"]
    assert snapshot["effective_prompt"] != snapshot["prompt"]
    renamed = client.put(
        "/api/v1/characters/" + character["id"],
        json={
            "expected_revision": character["revision"], "name": "Otra identidad", "voice_description": "Otra voz",
            "reference_asset_id": character["reference_asset"]["id"],
        },
    )
    assert renamed.status_code == 200, renamed.text
    edited = client.patch(
        "/api/v1/scenes/" + saved["id"],
        json={"expected_revision": saved["revision"], "prompt": "Texto cambiado", "parameters": {"audio_guides": []}},
    )
    assert edited.status_code == 200, edited.text
    run_tick(audio_remote)
    assert len(audio_remote.posts) == 1 and len(audio_remote.audio_uploads) == 1
    payload = audio_remote.audio_uploads[0]
    assert b'filename="' + job["id"].encode() + b'-audio-0.wav"' in payload
    assert b"RIFF" in payload and b"WAVE" in payload
    sent = audio_remote.posts[0]["prompt"]
    assert sent["fruti_audio_0"]["inputs"]["audio"] == "audio/voice-1.wav"
    assert sent["fruti_guide_0"]["inputs"]["frame_idx"] == 12
    assert sent["9"]["inputs"]["prompt"] == snapshot["effective_prompt"]
    assert "Otra identidad" not in sent["9"]["inputs"]["prompt"]
    assert audio_remote.calls.index(("GET", "/object_info/MiniMaxH3AddGuide")) < audio_remote.calls.index(("POST", "/upload/image"))
    assert audio_remote.calls.index(("POST", "/upload/image")) < audio_remote.calls.index(("POST", "/prompt"))
    with session_factory()() as db:
        assert db.get(GenerationJob, job["id"]).snapshot == snapshot
    assert client.get("/api/v1/assets/" + asset["id"] + "/content").content == wav_bytes()


def test_runtime_without_audio_guides_fails_before_upload_or_inference(client, audio_remote):
    connect(client)
    saved, _, _ = save_scene_audio(client, scene(client), with_character=False)
    del audio_remote.object_info["MiniMaxH3AddGuide"]
    job = submit(client, saved).json()
    run_tick(audio_remote)
    status = client.get("/api/v1/generations/" + job["id"]).json()
    assert status["state"] == "failed" and "MiniMaxH3AddGuide" in status["error"]
    assert not audio_remote.uploads and not audio_remote.posts
    run_tick(audio_remote)
    assert not audio_remote.posts


def test_tampered_audio_file_is_rejected_before_any_upload(client, audio_remote):
    connect(client)
    saved, asset, _ = save_scene_audio(client, scene(client), with_character=False)
    job = submit(client, saved).json()
    with session_factory()() as db:
        stored = db.get(Asset, asset["id"])
        original = get_settings().resolved_data_dir / stored.rel_path
    original.write_bytes(wav_bytes(level=2400))
    run_tick(audio_remote)
    status = client.get("/api/v1/generations/" + job["id"]).json()
    assert status["state"] == "failed" and "cambió" in status["error"]
    assert not audio_remote.uploads and not audio_remote.posts


def test_audio_timeout_does_not_resubmit_the_generated_scene(client, audio_remote):
    connect(client)
    saved, _, _ = save_scene_audio(client, scene(client), with_character=False)
    job = submit(client, saved).json()
    audio_remote.lose_response = True
    run_tick(audio_remote)
    assert client.get("/api/v1/generations/" + job["id"]).json()["state"] == "unknown"
    audio_remote.done = True
    run_tick(audio_remote)
    assert len(audio_remote.posts) == 1 and len(audio_remote.audio_uploads) == 1
    assert client.get("/api/v1/generations/" + job["id"]).json()["state"] == "completed"


def test_scene_without_audio_keeps_legacy_workflow_and_makes_no_capability_request(client, audio_remote):
    connect(client)
    original = scene(client, end=False)
    submit(client, original)
    audio_remote.object_info = {}
    run_tick(audio_remote)
    sent = audio_remote.posts[0]["prompt"]
    assert sent["9"]["inputs"]["prompt"] == original["prompt"]
    assert sent["15"]["inputs"]["conditioning"] == ["9", 0]
    assert "30" not in sent and "last_frame" not in sent["9"]["inputs"]
    assert not audio_remote.audio_uploads
    assert not any(path.startswith("/object_info") for _, path in audio_remote.calls)
