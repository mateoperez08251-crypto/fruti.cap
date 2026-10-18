"""New graph contract and mixed-version queue, without inference or weight downloads."""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from frutinovelas.prompts import ImageDraft
from frutinovelas.services.image_generation import prepare_image_graph
from frutinovelas.services.qwen21_workflow import EDIT_WORKFLOW, T2I_WORKFLOW, build_graph
from frutinovelas.worker import GenerationWorker
from test_character_images import qwen, setup_cast, submit_image  # noqa: F401
from test_generation import connect, scene


@pytest.mark.parametrize("count", [0, 1, 2])
def test_qwen21_native_reference_slots_canvas_and_saved_graph(count):
    graph = build_graph()
    graph["sample"] = {"class_type": "LoadImage", "inputs": {"image": "template.png"}}
    graph["encode"]["inputs"]["images.image_10"] = ["sample", 0]
    original = copy.deepcopy(graph)
    cast = [{"name": f"Personaje{i}", "description": ""} for i in range(count)]
    result = prepare_image_graph(
        graph, "Texto literal con tildes", cast, 123, [f"ref{i}.png" for i in range(count)], "job"
    )
    assert graph == original
    assert "template.png" not in json.dumps(result)
    assert result["encode"]["inputs"]["prompt"].startswith("Texto literal con tildes")
    assert result["sampler"]["inputs"]["negative"] == ["encode", 1]
    assert result["sampler"]["inputs"]["steps"] == 40
    assert result["sampler"]["inputs"]["cfg"] == 1
    assert result["sampler"]["inputs"]["seed"] == 123
    assert result["fruti_canvas"] == {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 1152, "height": 2048, "batch_size": 1},
    }
    assert result["save"]["inputs"]["images"] == ["rgb", 0]
    slots = {k: v for k, v in result["encode"]["inputs"].items() if k.startswith("images.")}
    assert slots == {f"images.image_{i}": [f"fruti_reference_{i}", 0] for i in range(1, count + 1)}
    for i in range(1, count + 1):
        assert f"<image{i}>" in result["encode"]["inputs"]["prompt"]


def test_qwen21_preferred_over_legacy_and_completed_through_worker(client, qwen):  # noqa: F811
    body = json.dumps(build_graph()).encode()
    for name in (T2I_WORKFLOW, EDIT_WORKFLOW):
        qwen.qwen[name] = body
        qwen.identity["workflows"][name] = hashlib.sha256(body).hexdigest()
    connect(client)
    s, _characters, _chapter = setup_cast(client, scene(client))
    response = submit_image(client, s)
    assert response.status_code == 202, response.text
    worker = GenerationWorker(client_factory=qwen.client)
    try:
        worker.tick()
        assert len(qwen.posts) == 1
        sent = qwen.posts[0]["prompt"]
        assert sent["model"]["inputs"]["unet_name"] == "qwen_image_2.1_bf16.safetensors"
        assert sent["encode"]["inputs"]["images.image_2"] == ["fruti_reference_2", 0]
        qwen.done = True
        worker.tick()
    finally:
        worker.stop()
    assert client.get(f"/api/v1/scenes/{s['id']}/image-generations").json()[0]["state"] == "completed"


def test_qwen21_tampered_workflow_never_falls_back(client, qwen):  # noqa: F811
    qwen.qwen[EDIT_WORKFLOW] = json.dumps(build_graph()).encode()
    qwen.identity["workflows"][EDIT_WORKFLOW] = "wrong"
    connect(client)
    s, _, _ = setup_cast(client, scene(client))
    assert submit_image(client, s).status_code == 422
    assert not qwen.posts


def test_qwen21_prompt_profile_supports_both_modes():
    fields = dict(
        subject="subject",
        composition="composition",
        environment="environment",
        lighting="lighting",
        materials="materials",
        expression="expression",
        starting_pose="pose",
    )
    assert ImageDraft(**fields).profile == "qwen21_bf16"
    assert (
        ImageDraft(
            **fields, mode="EDIT", has_reference_image=True, preserve=["identity"], changes=["background"]
        ).profile
        == "qwen21_bf16"
    )


def test_colab_and_remote_include_same_qwen21_builder():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_colab_notebook as notebook
    import build_remote_kit as kit
    import fruti_remote as remote
    import validate_workflows as vw

    assert "qwen21_bf16" in remote.perfiles_activos(remote.DEFAULT_CFG)
    assert "qwen21_bf16" not in remote.perfiles_activos({**remote.DEFAULT_CFG, "qwen21": False})
    path = "src/frutinovelas/services/qwen21_workflow.py"
    assert path in kit.FILES
    assert path in dict(notebook.EMBEDDED)
    info = {
        n["class_type"]: {"input": {"required": {}}, "output": ["ANY"] * 3} for n in build_graph().values()
    }
    info["TextEncodeQwenImage21"]["input"]["required"] = {"images": ["AUTOGROW"]}
    assert not vw.validate_api_graph(build_graph(), info)["errors"]
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "config/models_manifest.lock.json").read_text(encoding="utf-8"))
    profile = manifest["profiles"]["qwen21_bf16"]
    assert sum(manifest["components"][key]["size"] for key in profile["components"]) == 32440124920


def test_generated_notebook_is_current_and_code_cells_compile():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_colab_notebook as notebook

    root = Path(__file__).resolve().parents[1]
    path = root / "notebooks/FRUTINOVELAS_ComfyUI_Imagenes_H3_Colab.ipynb"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == notebook.build("colab")
    assert path.read_bytes() == (root.parent / path.name).read_bytes()
    for i, cell in enumerate(stored["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        if source.startswith("%%writefile"):
            continue
        compile(source, f"cell-{i}", "exec")
