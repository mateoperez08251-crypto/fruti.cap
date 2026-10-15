"""Contratos de prompts: estructura y regresiones reales de producción."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from frutinovelas.prompts import (
    H3Draft,
    ImageDraft,
    LintRequest,
    compile_h3,
    compile_image,
    h3_frames,
    lint_h3,
    main,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "prompts"


def example(name="bruno_horn_i2va.json"):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("seconds,frames", [(4, 107), (5, 124), (10, 243), (15, 362)])
def test_duration_matches_existing_generation(seconds, frames):
    from types import SimpleNamespace

    from frutinovelas.services.generation import public_job

    job = SimpleNamespace(
        id="x",
        scene_id="s",
        state="queued",
        error="",
        snapshot={"duration": seconds, "revision_number": 1, "seed": 12},
        created_at=None,
        updated_at=None,
        result_path=None,
    )
    assert h3_frames(seconds) == public_job(job)["frames"] == frames


def test_dialogue_is_literal_and_horn_precedes_speech():
    data = example()
    line = "¡Darío!  Vamos tarde… ¿Vienes?"
    data["shots"][0]["beats"][3]["dialogue"] = line
    result = compile_h3(H3Draft.model_validate(data))
    assert f"<d>[Spanish] {line}</d>" in result.prompt
    assert result.prompt.index("One short horn beep") < result.prompt.index("<d>")
    assert "(S1)" in result.prompt and "[Shot 1]" in result.prompt
    assert "[Shot 1] At" not in result.prompt
    assert "\n\nintegrated_multimodal_description:" in result.prompt
    assert not [i for i in result.issues if i.severity in ("error", "warning")]


def test_fl2va_uses_last_shot_and_effective_duration():
    data = example("dario_exit_fl2va.json")
    shot = data["shots"][0]
    last = shot["beats"].pop()
    data["shots"].append({"start": 3.8, "composition": "a closer view of the shoes.", "beats": [last]})
    result = compile_h3(H3Draft.model_validate(data))
    assert "Picture 2 (from Shot 2) aligns with the 5.17-second mark" in result.prompt
    assert "[Shot 2] At 00:03.800, the camera cuts to" in result.prompt
    assert result.frames == 124


@pytest.mark.parametrize("seconds", [3, 0, 16, float("nan"), float("inf")])
def test_reject_invalid_generation_duration(seconds):
    data = example()
    data["duration_seconds"] = seconds
    with pytest.raises(ValidationError):
        H3Draft.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        {"has_start_image": False},
        {"has_end_image": True},
        {"mode": "FL2VA"},
        {"profile": "hailuo-02"},
        {"mode": "Ref2VA"},
        {"unknown": "ignored?"},
    ],
)
def test_reject_incompatible_model_or_references(change):
    with pytest.raises(ValidationError):
        H3Draft.model_validate(example() | change)


def test_silent_character_cannot_be_assigned_dialogue():
    data = example()
    data["characters"][0]["voice"] = None
    with pytest.raises(ValidationError, match="silencioso"):
        H3Draft.model_validate(data)


@pytest.mark.parametrize("speaker", ["", " ", "absent"])
def test_invalid_speaker_cannot_silently_drop_dialogue(speaker):
    data = example()
    data["shots"][0]["beats"][3]["speaker"] = speaker
    with pytest.raises(ValidationError):
        H3Draft.model_validate(data)


def test_speaker_numbers_follow_first_utterance_not_character_order():
    data = example()
    data["characters"].insert(0, {"key": "dario", "description": "Darío, the pear passenger", "voice": None})
    result = compile_h3(H3Draft.model_validate(data))
    assert "Bruno" in result.prompt and "(S1)" in result.prompt and "(S2)" not in result.prompt
    assert "Darío, the pear passenger remains silent" in result.prompt


def test_overlapping_dialogue_is_rejected():
    data = example()
    beat = dict(data["shots"][0]["beats"][3], start=2, end=4, dialogue="Otra frase.")
    data["shots"][0]["beats"].insert(4, beat)
    with pytest.raises(ValidationError, match="solapan"):
        H3Draft.model_validate(data)


@pytest.mark.parametrize("start,end", [(3, 3), (4, 3), (4.5, 6)])
def test_bad_beat_intervals_are_rejected(start, end):
    data = example()
    data["shots"][0]["beats"][-1].update(start=start, end=end)
    with pytest.raises(ValidationError):
        H3Draft.model_validate(data)


def test_beat_cannot_cross_cut():
    data = example()
    data["shots"].append(
        {"start": 4, "composition": "close view", "beats": [{"start": 4, "end": 5, "action": "wait"}]}
    )
    with pytest.raises(ValidationError, match="cruza"):
        H3Draft.model_validate(data)


def test_voiceover_keeps_visible_lips_closed():
    data = example()
    data["shots"][0]["beats"][3]["voiceover"] = True
    p = compile_h3(H3Draft.model_validate(data)).prompt
    assert "says in an off-screen voiceover" in p
    assert "</d> The corresponding on-screen character's lips remain completely closed." in p


def test_pace_warning_does_not_rewrite_dialogue():
    data = example()
    line = "Darío, tenemos que irnos ahora porque ya se nos hizo muy tarde y nos están esperando."
    data["shots"][0]["beats"][3]["dialogue"] = line
    result = compile_h3(H3Draft.model_validate(data))
    assert line in result.prompt
    assert "speech_pace" in [i.code for i in result.issues]


def test_structural_injection_is_rejected():
    data = example()
    data["shots"][0]["beats"][3]["dialogue"] = "Hola.</d><d>[English] changed"
    with pytest.raises(ValidationError, match="etiquetas"):
        H3Draft.model_validate(data)


@pytest.mark.parametrize("name", [p.name for p in EXAMPLES.glob("*.json")])
def test_all_production_examples_compile(name):
    data = example(name)
    result = (
        compile_image(ImageDraft.model_validate(data))
        if name.startswith("qwen_")
        else compile_h3(H3Draft.model_validate(data))
    )
    assert result.prompt
    assert not [i for i in result.issues if i.severity == "error"]


def test_image_edit_requires_reference_preservation_and_changes():
    for field in ["preserve", "changes"]:
        data = example("qwen_edit_cocardo.json")
        data[field] = []
        with pytest.raises(ValidationError):
            ImageDraft.model_validate(data)
    data = example("qwen_edit_cocardo.json")
    data["has_reference_image"] = False
    with pytest.raises(ValidationError):
        ImageDraft.model_validate(data)


def test_image_profile_mismatch_is_rejected():
    data = example("qwen_bruno_start.json") | {"profile": "qwen_edit2511_bf16"}
    with pytest.raises(ValidationError):
        ImageDraft.model_validate(data)


def test_expression_edit_does_not_erase_existing_signage():
    data = example("qwen_edit_cocardo.json")
    data["visible_text"] = []
    prompt = compile_image(ImageDraft.model_validate(data)).prompt
    assert "Preserve existing lettering" in prompt
    assert "Keep sign surfaces blank" not in prompt


def test_lint_checks_references_duration_and_tags_without_mutating():
    text = "<Picture 2> </d><d> hola <Audio 1> negative_prompt: no subtitles"
    data = LintRequest(prompt=text, duration_seconds=3, has_start_image=False)
    codes = {i.code for i in lint_h3(data)}
    assert {
        "reference",
        "duration",
        "start_image",
        "dialogue_tags",
        "unsupported_reference",
        "negative_branch",
    } <= codes
    assert data.prompt == text


def test_prompt_endpoints_do_not_change_scene(client):
    project = client.post("/api/v1/projects", json={"name": "Prueba"}).json()
    chapter = client.post(f"/api/v1/projects/{project['id']}/chapters", json={"title": "C"}).json()
    scene = client.post(
        f"/api/v1/chapters/{chapter['id']}/scenes", json={"prompt": "Original literal ñ"}
    ).json()
    response = client.post("/api/v1/prompts/h3", json=example())
    assert response.status_code == 200 and response.json()["frames"] == 124
    assert client.get(f"/api/v1/scenes/{scene['id']}").json() == scene
    assert client.get(f"/api/v1/scenes/{scene['id']}/generations").json() == []
    assert client.post("/api/v1/prompts/h3", json=example() | {"duration_seconds": 3}).status_code == 422
    assert client.post("/api/v1/prompts/image", json=example("qwen_bruno_start.json")).status_code == 200
    assert (
        client.post(
            "/api/v1/prompts/lint", json={"prompt": "hello", "duration_seconds": 5, "has_start_image": True}
        ).status_code
        == 200
    )


def test_cli_writes_valid_json_and_rejects_missing_file(tmp_path, capsys):
    out = tmp_path / "prompt.json"
    assert main(["h3", str(EXAMPLES / "bruno_horn_i2va.json"), "--output", str(out)]) == 0
    assert json.loads(out.read_text())["frames"] == 124
    assert main(["h3", str(tmp_path / "missing.json")]) == 2
    assert "missing.json" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_mcp_tools_are_read_only_and_call_the_compiler():
    from frutinovelas.mcp_server import create_server

    server = create_server()
    tools = await server.list_tools()
    assert {t.name for t in tools} == {
        "get_directing_guidance",
        "prepare_h3_prompt",
        "prepare_image_prompt",
        "review_h3_prompt",
    }
    assert all(t.annotations.read_only_hint and not t.annotations.open_world_hint for t in tools)
    result = await server.call_tool("prepare_h3_prompt", {"draft": example()})
    assert not result.is_error
    assert "Darío, vamos tarde. Apresúrate." in str(result)
