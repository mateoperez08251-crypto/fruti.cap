import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from scripts import flow_image_job as job


def test_preset_is_reused_but_scene_is_explicit_and_prompt_stays_literal(tmp_path):
    preset = tmp_path / "style.json"
    preset.write_text(json.dumps({"style": "Línea azul; papel.", "scene": "No usar esta escena antigua"}), encoding="utf-8")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"request_id": str(uuid4()), "preset_path": str(preset),
                                   "scene": "¿Qué pasaría? — dijo María."}), encoding="utf-8")
    result = job.read_request(request)
    assert result["prompt"] == "Línea azul; papel.\n\nEscena: ¿Qué pasaría? — dijo María."
    assert result["outputs"] == 1
    request.write_text(json.dumps({"request_id": str(uuid4()), "preset_path": str(preset)}), encoding="utf-8")
    with pytest.raises(ValueError, match="escena"):
        job.read_request(request)


@pytest.mark.parametrize("state", ["sending", "creating_project"])
def test_uncertain_submission_or_creation_is_not_repeated(tmp_path, state):
    path = tmp_path / "job.json"
    path.write_text(json.dumps({"request": {"prompt": "literal"}, "state": state}))
    with pytest.raises(ValueError, match="incierto"):
        job.load_job(path, {"prompt": "literal"})


def test_request_id_cannot_be_reused_for_changed_prompt(tmp_path):
    path = tmp_path / "job.json"
    path.write_text(json.dumps({"request": {"prompt": "original"}, "state": "submitted"}))
    with pytest.raises(ValueError, match="otra solicitud"):
        job.load_job(path, {"prompt": "edited"})


def test_concurrent_process_cannot_acquire_same_job(tmp_path):
    path = tmp_path / "job.json"
    with job.job_lock(path):
        with pytest.raises(FileExistsError), job.job_lock(path):
            pytest.fail("Second process acquired the same request")
    assert not path.with_suffix(".lock").exists()


def test_interruption_at_click_persists_uncertainty_and_never_resends(tmp_path):
    path = tmp_path / "job.json"
    state = {"request": {"prompt": "¡Texto literal!"}, "state": "configured"}
    text = []
    clicks = []

    def click():
        clicks.append("generate")
        assert json.loads(path.read_text())["state"] == "sending"
        raise TimeoutError("Reception unknown")

    editor = SimpleNamespace(fill=text.append, inner_text=lambda: text[-1])
    page = SimpleNamespace(get_by_role=lambda role, **kwargs: editor if role == "textbox"
                           else SimpleNamespace(click=click))
    with pytest.raises(TimeoutError):
        job.submit_once(page, state, path)
    with pytest.raises(ValueError, match="ya se envió"):
        job.submit_once(page, state, path)
    assert clicks == ["generate"]
    assert text == ["¡Texto literal!"]
