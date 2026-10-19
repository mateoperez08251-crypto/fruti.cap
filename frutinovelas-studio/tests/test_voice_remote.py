"""Remote voice kit and notebook contracts; no GPU, model downloads or network."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from frutinovelas.services.voice_workflow import (
    VOICE_UNET,
    VOICE_UNET_SHA256,
    VOICE_WORKFLOW,
    validate_voice_workflow,
)
from test_voice_generation import voice_base_workflow, voice_node_info

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_colab_notebook as notebook_builder  # noqa: E402
import build_remote_kit as kit_builder  # noqa: E402
import fruti_remote as remote  # noqa: E402

VOICE_COMPONENT = "h3_diffusion_ref2va_pruned_int8"


def remote_export_inputs():
    """Complete the shared fixture's ordinary sampler and output metadata."""
    graph = voice_base_workflow()
    graph["13"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}}
    graph["14"]["inputs"].update(model=["5", 0], denoise=1)
    graph["16"]["inputs"].update(noise=["12", 0], sampler=["13", 0], sigmas=["14", 0])
    graph["17"] = {"class_type": "VAEDecode", "inputs": {"samples": ["16", 0], "vae": ["7", 0]}}
    graph["20"]["inputs"]["video"] = ["19", 0]
    info = voice_node_info()
    ordinary_outputs = {
        "LoadImage": ["IMAGE", "MASK"], "UNETLoader": ["MODEL"], "CLIPLoader": ["CLIP"],
        "VAELoader": ["VAE"], "MiniMaxH3ImageToVideo": ["CONDITIONING", "LATENT"],
        "RandomNoise": ["NOISE"], "KSamplerSelect": ["SAMPLER"], "BasicScheduler": ["SIGMAS"],
        "BasicGuider": ["GUIDER"], "SamplerCustomAdvanced": ["LATENT", "LATENT"],
        "VAEDecode": ["IMAGE"], "VAEDecodeAudio": ["AUDIO"], "CreateVideo": ["VIDEO"],
        "SaveVideo": [], "PrimitiveFloat": ["FLOAT"], "ComfyMathExpression": ["INT", "FLOAT"],
    }
    for class_type, outputs in ordinary_outputs.items():
        info[class_type] = {"input": {"required": {}}, "output": outputs}
    # The real generic validator must also see the installed model choices.
    manifest = remote.manifest()
    for destination, class_type, field in (
        ("diffusion_models", "UNETLoader", "unet_name"),
        ("text_encoders", "CLIPLoader", "clip_name"),
        ("vae", "VAELoader", "vae_name"),
    ):
        names = [Path(component["path"]).name for component in manifest["components"].values() if component["dest"] == destination]
        info[class_type]["input"]["required"][field] = [names, {}]
    info["LoadImage"]["input"]["required"]["image"] = [[], {"image_upload": True}]
    return graph, info


@pytest.fixture
def remote_export(tmp_path, monkeypatch):
    data = tmp_path / "remote-data"
    api = data / "workflows" / "api"
    api.mkdir(parents=True)
    for name, path in {
        "DATA_DIR": data, "API_DIR": api, "CONFIG_FILE": data / "config.json",
        "INFORME_FILE": data / "export.json", "IDENTITY_FILE": data / "identity.json",
        "PIP_MARKER": data / "installed.txt",
    }.items():
        monkeypatch.setattr(remote, name, path)
    monkeypatch.setattr(remote, "ensure_dirs", lambda: None)
    remote.save_json(remote.CONFIG_FILE, {**remote.DEFAULT_CFG, "voces_personajes": True, "qwen21": False})
    graph, info = remote_export_inputs()
    monkeypatch.setattr(remote, "exportar", lambda *_args: copy.deepcopy(graph))
    return graph, info


@pytest.mark.parametrize("profile", ["h3_balanced_default", "h3_quality_bf16_optional"])
def test_voice_cli_flag_is_persistent_and_only_adds_reference_weights(tmp_path, monkeypatch, profile):
    monkeypatch.setattr(remote, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(remote, "ensure_dirs", lambda: None)
    observed = []
    monkeypatch.setattr(remote, "cmd_models", lambda _args: observed.append(remote.cfg()))
    original = {**remote.DEFAULT_CFG, "perfil_video": profile, "qwen_t2i": True, "qwen_edit": "fp8mixed"}
    remote.save_json(remote.CONFIG_FILE, original)
    baseline = remote.componentes(original)
    assert not remote.DEFAULT_CFG["voces_personajes"]

    assert remote.main(["models", "--voces-personajes", "si"]) == 0
    enabled = remote.cfg()
    assert enabled == {**original, "voces_personajes": True}
    assert remote.perfiles_activos(enabled) == [profile, "h3_voice_references", "qwen21_bf16", "qwen2512_t2i", "qwen_edit2511_fp8mixed"]
    components = remote.componentes(enabled)
    assert set(components) - set(baseline) == {VOICE_COMPONENT}
    assert set(baseline) <= set(components) and len(components) == len(set(components))
    assert [key for key in components if key != VOICE_COMPONENT] == baseline
    manifest = remote.manifest()
    component = manifest["components"][VOICE_COMPONENT]
    assert manifest["profiles"]["h3_voice_references"]["components"] == [VOICE_COMPONENT]
    assert Path(component["path"]).name == VOICE_UNET
    assert component["sha256"] == VOICE_UNET_SHA256
    assert manifest["repos"][component["repo_id"]] == "e5eb578a89295337b8ff433a035929ce0279e0b6"

    assert remote.main(["models"]) == 0  # Omission retains the saved choice.
    assert observed[-1]["voces_personajes"]
    assert remote.main(["models", "--voces-personajes", "no"]) == 0
    assert remote.cfg() == original
    assert remote.componentes(remote.cfg()) == baseline


@pytest.mark.parametrize("profile", ["h3_balanced_default", "h3_quality_bf16_optional"])
def test_remote_voice_export_preserves_visual_flows_and_publishes_verified_hash(remote_export, profile):
    base, info = remote_export
    original = copy.deepcopy(base)
    remote.save_json(remote.CONFIG_FILE, {**remote.cfg(), "perfil_video": profile})
    report = remote.exportar_y_validar(info, forzar=True)
    expected_names = set(remote.profile()["workflow_api_files"].values()) | {VOICE_WORKFLOW}
    assert set(report["flujos"]) == expected_names
    assert base == original
    voice_bytes = (remote.API_DIR / VOICE_WORKFLOW).read_bytes()
    voice_graph = json.loads(voice_bytes)
    validate_voice_workflow(voice_graph)
    assert not remote.vw.validate_api_graph(voice_graph, info)["errors"]
    assert voice_graph["5"]["inputs"]["unet_name"] == VOICE_UNET
    assert voice_graph["9"]["inputs"]["ref_images.ref_image_0"] == ["1", 0]
    assert voice_graph["9"]["inputs"]["ref_images.ref_image_1"] == ["30", 0]
    assert not any(key.startswith("ref_audios") for key in voice_graph["9"]["inputs"])
    for mode, filename in remote.profile()["workflow_api_files"].items():
        saved = remote.load_json(remote.API_DIR / filename)
        assert saved["9"]["class_type"] == "MiniMaxH3ImageToVideo"
        assert ("last_frame" in saved["9"]["inputs"]) == (mode == "fl2va")
        for node in ("6", "7", "8", "14", "19", "28", "29"):
            assert voice_graph[node] == saved[node]
    digest = hashlib.sha256(voice_bytes).hexdigest()
    assert report["flujos"][VOICE_WORKFLOW]["sha256"] == digest
    assert report["flujos"][VOICE_WORKFLOW]["modo"] == "ref2va"
    identity = remote.escribir_identidad({"system": {}}, report)
    assert identity["workflows"][VOICE_WORKFLOW] == digest
    assert identity["modelos"][VOICE_COMPONENT] == {"archivo": VOICE_UNET, "sha256": VOICE_UNET_SHA256}
    assert identity["estado_compatibilidad"] == "pendiente_prueba_real"


@pytest.mark.parametrize("incompatibility", ["missing_node", "too_few_audio_inputs"])
def test_incompatible_voice_node_stops_before_connection_publication(remote_export, monkeypatch, incompatibility):
    _base, info = remote_export
    if incompatibility == "missing_node":
        del info["MiniMaxH3ReferenceToVideo"]
    else:
        info["MiniMaxH3ReferenceToVideo"]["input"]["optional"]["ref_audios"][1]["template"]["max"] = 2
    remote.PIP_MARKER.write_text(remote.COMFY_COMMIT)
    monkeypatch.setattr(remote, "instalar_atajo", lambda: None)
    monkeypatch.setattr(remote, "arrancar_comfy", lambda: ({"system": {}}, info))

    def forbidden(*_args, **_kwargs):
        pytest.fail("An incompatible voice graph must not reach credentials, publication or installation.")

    for name in ("cmd_install", "obtener_token", "escribir_identidad", "arrancar_gateway", "acceso_publico"):
        monkeypatch.setattr(remote, name, forbidden)
    with pytest.raises(SystemExit) as rejected:
        remote.main(["start", "--voces-personajes", "si", "--reexportar"])
    assert rejected.value.code == 1
    assert not (remote.API_DIR / VOICE_WORKFLOW).exists()
    report = remote.load_json(remote.INFORME_FILE)
    assert VOICE_WORKFLOW not in report["flujos"] and report["clave"] is None


def test_voice_export_cache_rechecks_hash_and_native_autogrow_contract(remote_export):
    _base, info = remote_export
    report = remote.exportar_y_validar(info, forzar=True)
    names = set(report["flujos"])
    assert remote.cache_exportacion_valida(report, report["clave"], names, info)
    path = remote.API_DIR / VOICE_WORKFLOW
    original = path.read_bytes()
    path.write_bytes(original + b"\n")
    assert not remote.cache_exportacion_valida(report, report["clave"], names, info)
    path.write_bytes(original)
    info["MiniMaxH3ReferenceToVideo"]["input"]["optional"]["ref_audios"][1]["template"]["max"] = 2
    # The published graph has no audio yet: generic link validation alone is insufficient.
    assert not remote.vw.validate_api_graph(json.loads(original), info)["errors"]
    assert not remote.cache_exportacion_valida(report, report["clave"], names, info)


def test_remote_archive_contains_an_independently_importable_stdlib_voice_helper(tmp_path, monkeypatch):
    archive = tmp_path / "kit.tar.gz"
    monkeypatch.setattr(kit_builder, "OUT", archive)
    assert kit_builder.main() == 0
    expected = {f"{kit_builder.PREFIX}/{name}" for name in (*kit_builder.FILES, kit_builder.UI, "LEEME.txt")}
    with tarfile.open(archive, "r:gz") as packed:
        assert set(packed.getnames()) == expected
        for member in packed.getmembers():
            assert member.isfile()
            content = packed.extractfile(member).read()
            target = tmp_path / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    extracted = tmp_path / kit_builder.PREFIX
    helper = extracted / "src/frutinovelas/services/voice_workflow.py"
    assert helper.read_bytes() == (ROOT / "src/frutinovelas/services/voice_workflow.py").read_bytes().replace(b"\r\n", b"\n")
    assert (extracted / kit_builder.UI).read_bytes() == (ROOT / kit_builder.UI).read_bytes()
    program = """
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
import fruti_remote
from frutinovelas.services import voice_workflow
assert Path(voice_workflow.__file__).is_relative_to(root)
fruti_remote.verificar_kit()
print(voice_workflow.VOICE_WORKFLOW)
"""
    # -I ignores the caller's PYTHONPATH; -S prevents installed site-packages
    # from hiding a missing dependency in the self-contained remote package.
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", program, str(extracted)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == VOICE_WORKFLOW


def test_colab_notebook_is_rebuildable_and_contains_valid_embedded_voice_code():
    notebook = notebook_builder.build("colab")
    saved = json.loads(notebook_builder.PLATFORMS["colab"]["out"].read_text(encoding="utf-8"))
    assert notebook == saved
    embedded = {}
    ui_text = None
    kit = notebook_builder.PLATFORMS["colab"]["kit"]
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        assert cell["execution_count"] is None and cell["outputs"] == []
        source = "".join(cell["source"])
        if source.startswith("%%writefile "):
            magic, content = source.split("\n", 1)
            relative = magic.removeprefix("%%writefile " + kit + "/")
            assert relative != magic
            embedded[relative] = content
            if relative.endswith(".py"):
                ast.parse(content.lstrip("\ufeff"), filename=relative)
            elif relative.endswith(".json"):
                json.loads(content)
        else:
            tree = ast.parse(source, filename=cell["id"])
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "UI_TEXT" for target in node.targets):
                    ui_text = ast.literal_eval(node.value)
    assert set(embedded) == {relative for relative, _source in notebook_builder.EMBEDDED}
    for relative, source in notebook_builder.EMBEDDED:
        assert embedded[relative] == source.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n")
    assert "src/frutinovelas/services/voice_workflow.py" in embedded
    assert ui_text.encode("utf-8") == notebook_builder.UI_FILE.read_bytes()
    manifest = json.loads(embedded["config/models_manifest.lock.json"])
    assert manifest["components"][VOICE_COMPONENT]["sha256"] == VOICE_UNET_SHA256
    assert "ACTIVAR_VOCES_PERSONAJES = True" in notebook_builder.CONFIG_HEAD_COLAB
    assert "validate_voice_node_info(OBJECT_INFO)" in notebook_builder.CELL_EXPORT
