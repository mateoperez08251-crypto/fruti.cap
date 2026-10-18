"""Reusable character voices through native H3 Ref2VA, without a TTS service.

This module intentionally uses only the standard library: the remote kit also
imports derive_voice_workflow to publish the same graph contract as the app.
Native node contract: ComfyUI 3541246a9c997f4b8c32f9f88f3c985d02021c79,
comfy_extras/nodes_minimax_h3.py and comfy_api/latest/_io.py::Autogrow.
Reference audio supplies timbre context; it is not placed on the output timeline.
"""

from __future__ import annotations

import copy
import json
import math
import re

VOICE_WORKFLOW = "H3_VOZ_PERSONAJES.api.json"
VOICE_UNET = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
VOICE_UNET_SHA256 = "9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779"
START_GUIDE = "fruti_voice_start"
END_GUIDE = "fruti_voice_end"
MAX_VOICES = 3


class VoiceWorkflowError(ValueError):
    """A permanent, user-readable preparation failure before /prompt."""


def _node_inputs(graph, node_id, class_type):
    node = graph.get(node_id) if isinstance(graph, dict) else None
    if not isinstance(node, dict) or node.get("class_type") != class_type or not isinstance(node.get("inputs"), dict):
        raise VoiceWorkflowError(f"El flujo de voces no contiene {class_type} en el nodo {node_id}.")
    return node["inputs"]


def _shared_contract(graph):
    for node_id, class_type in {
        "1": "LoadImage", "5": "UNETLoader", "6": "CLIPLoader", "7": "VAELoader", "8": "VAELoader",
        "12": "RandomNoise", "14": "BasicScheduler", "15": "BasicGuider", "16": "SamplerCustomAdvanced",
        "18": "VAEDecodeAudio", "19": "CreateVideo", "20": "SaveVideo", "28": "PrimitiveFloat", "30": "LoadImage",
    }.items():
        _node_inputs(graph, node_id, class_type)
    if (
        graph["8"]["inputs"].get("vae_name") != "minimax_h3_audio_vae_fp32.safetensors"
        or graph["14"]["inputs"].get("steps") != 20
        or graph["19"]["inputs"].get("fps") != 24
        or graph["16"]["inputs"].get("latent_image") != ["9", 1]
        or graph["18"]["inputs"].get("vae") != ["8", 0]
        or graph["18"]["inputs"].get("samples") != ["16", 0]
        or graph["19"]["inputs"].get("audio") != ["18", 0]
    ):
        raise VoiceWorkflowError("El flujo de voces debe conservar el audio VAE, la salida nativa H3, 24 fps y 20 pasos.")


def derive_voice_workflow(base_graph, unet_name):
    """Return a private Ref2VA graph, with both visual anchors and no sample audio.

The kit passes its already overridden, validated start/end FL2VA graph. Encoder,
VAEs, sampler, canvas, duration calculation and output are preserved. Only the
diffusion weights, conditioning node and image-anchor connections change.
"""
    if unet_name != VOICE_UNET:
        raise VoiceWorkflowError("El perfil de voces requiere el checkpoint Ref2VA INT8 verificado.")
    _shared_contract(base_graph)
    inputs = _node_inputs(base_graph, "9", "MiniMaxH3ImageToVideo")
    if (
        (inputs.get("width"), inputs.get("height")) != (576, 1024)
        or inputs.get("clip") != ["6", 0]
        or inputs.get("vae") != ["7", 0]
        or "length" not in inputs
        or inputs.get("first_frame") != ["1", 0]
        or inputs.get("last_frame") != ["30", 0]
        or base_graph["15"]["inputs"].get("conditioning") != ["9", 0]
        or START_GUIDE in base_graph or END_GUIDE in base_graph
    ):
        raise VoiceWorkflowError("La variante de voces debe derivarse del flujo H3 original de inicio y final.")
    graph = copy.deepcopy(base_graph)
    graph["5"]["inputs"]["unet_name"] = unet_name
    graph["9"]["class_type"] = "MiniMaxH3ReferenceToVideo"
    graph["9"]["inputs"] = {
        key: copy.deepcopy(inputs[key]) for key in ("clip", "vae", "prompt", "width", "height", "length")
    }
    graph["9"]["inputs"].update({
        "audio_vae": ["8", 0], "ref_image_size": "match",
        "ref_images.ref_image_0": ["1", 0], "ref_images.ref_image_1": ["30", 0],
    })
    previous = ["9", 0]
    for node_id, image_id, frame in ((START_GUIDE, "1", 0), (END_GUIDE, "30", -1)):
        graph[node_id] = {
            "class_type": "MiniMaxH3AddGuide",
            "inputs": {"positive": previous, "latent": ["9", 1], "vae": ["7", 0], "image": [image_id, 0], "frame_idx": frame},
        }
        previous = [node_id, 0]
    graph["15"]["inputs"]["conditioning"] = previous
    validate_voice_workflow(graph)
    return graph


def validate_voice_workflow(graph):
    """Validate the published, unbound graph, not a graph with sample placeholders."""
    _shared_contract(graph)
    inputs = _node_inputs(graph, "9", "MiniMaxH3ReferenceToVideo")
    expected = {
        "clip": ["6", 0], "vae": ["7", 0], "audio_vae": ["8", 0],
        "width": 576, "height": 1024, "ref_image_size": "match",
        "ref_images.ref_image_0": ["1", 0], "ref_images.ref_image_1": ["30", 0],
    }
    if (
        graph["5"]["inputs"].get("unet_name") != VOICE_UNET
        or any(inputs.get(key) != value for key, value in expected.items())
        or "length" not in inputs or not isinstance(inputs.get("prompt"), str)
        or set(inputs) - (set(expected) | {"prompt", "length"})
        or graph["15"]["inputs"].get("conditioning") != [END_GUIDE, 0]
    ):
        raise VoiceWorkflowError("El flujo publicado no coincide con Ref2VA y sus referencias de voz e imagen.")
    previous = ["9", 0]
    for node_id, image_id, frame in ((START_GUIDE, "1", 0), (END_GUIDE, "30", -1)):
        guide = _node_inputs(graph, node_id, "MiniMaxH3AddGuide")
        if guide != {"positive": previous, "latent": ["9", 1], "vae": ["7", 0], "image": [image_id, 0], "frame_idx": frame}:
            raise VoiceWorkflowError("El flujo de voces no conserva las anclas visuales de inicio y final.")
        previous = [node_id, 0]
    if any(not isinstance(node, dict) or node.get("class_type") == "LoadAudio" for node in graph.values()):
        raise VoiceWorkflowError("El flujo publicado contiene un audio de ejemplo sin asignar.")


def validate_voice_references(references):
    if not isinstance(references, list) or len(references) > MAX_VOICES:
        raise VoiceWorkflowError("Cada escena admite hasta tres voces de personajes.")
    characters = set()
    total = 0.0
    for reference in references:
        if not isinstance(reference, dict):
            raise VoiceWorkflowError("La revisión contiene una referencia de voz no válida.")
        asset = reference.get("asset")
        character_id = reference.get("character_id")
        if (
            not isinstance(character_id, str) or not character_id or character_id in characters
            or not isinstance(reference.get("character_name"), str) or not reference["character_name"].strip()
            or not isinstance(reference.get("voice_description", ""), str)
            or not isinstance(reference.get("asset_id"), str)
            or not isinstance(asset, dict) or asset.get("id") != reference["asset_id"]
            or asset.get("kind") != "audio" or not isinstance(asset.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])
        ):
            raise VoiceWorkflowError("Falta la muestra o la identidad de una voz guardada. Vuelve a guardar la selección.")
        duration = asset.get("duration_seconds")
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 2 <= duration <= 15:
            raise VoiceWorkflowError("Cada muestra de voz para Ref2VA debe durar entre 2 y 15 segundos.")
        characters.add(character_id)
        total += duration
    if total > 15 + 1e-6:
        raise VoiceWorkflowError("Las muestras de las voces seleccionadas suman más de 15 segundos.")


def _speaker_label(prompt, name):
    """Reuse an explicit adjacent speaker ID; never guess or renumber one."""
    escaped = re.escape(name)
    labels = set(re.findall(rf"(?<!\w){escaped}\s*\(S(\d+)\)", prompt, re.IGNORECASE))
    labels.update(re.findall(rf"\(S(\d+)\)\s*{escaped}(?!\w)", prompt, re.IGNORECASE))
    return f" (S{next(iter(labels))})" if len(labels) == 1 else ""


def effective_voice_prompt(prompt, references, *, end_frame=False):
    """Compile native Ref2VA reference roles while preserving all literal dialogue.

The original prompt remains independently stored in the revision/job. Field
headings may change in this effective representation; dialogue is never rewritten.
"""
    validate_voice_references(references)
    if not references:
        return prompt
    directions = re.sub(r"<d>.*?</d>", "", prompt, flags=re.DOTALL)
    if re.search(r"<Audio\s+\d+>", directions, re.IGNORECASE):
        raise VoiceWorkflowError("Para usar las voces guardadas, identifica a los personajes por nombre; el programa asigna las etiquetas <Audio N>.")
    fields = {}
    pattern = r"(?m)^[ \t]*(subject_definitions|summary|retention_analysis|integrated_multimodal_description|detailed_description|overall_soundscape|non_diegetic_music)[ \t]*:"
    # Dialogue can contain newlines or words such as "summary:". Mask it at the
    # same offsets while locating headings, and slice only the original string.
    masked = re.sub(r"<d>.*?</d>", lambda match: re.sub(r"[^\n]", " ", match.group()), prompt, flags=re.DOTALL)
    matches = list(re.finditer(pattern, masked))
    prefix = prompt[:matches[0].start()] if matches else prompt
    for index, match in enumerate(matches):
        key = match.group(1)
        if key in fields:
            raise VoiceWorkflowError("El prompt repite una sección. Guarda una única descripción antes de usar voces.")
        fields[key] = prompt[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(prompt)]
    if "integrated_multimodal_description" in fields and "detailed_description" in fields:
        raise VoiceWorkflowError("El prompt mezcla dos formatos de descripción. Guarda una única descripción de escena.")
    body = prefix + fields.get("detailed_description", fields.get("integrated_multimodal_description", ""))
    definitions = [fields.get("subject_definitions", "").strip(), "<Picture 1> is the supplied opening frame of the target scene."]
    retention = [fields.get("retention_analysis", "").strip(), "<Picture 1>: fully_preserved - preserve its opening composition and visible cast."]
    bindings = []
    if end_frame:
        definitions.append("<Picture 2> is the supplied final frame of the target scene.")
        retention.append("<Picture 2>: fully_preserved - use its composition at the end of the scene.")
    for index, reference in enumerate(references, 1):
        name = " ".join(reference["character_name"].split())
        character = "the character named " + json.dumps(name, ensure_ascii=False)
        speaker = character + _speaker_label(directions, name)
        definitions.append(f"<Audio {index}> is the voice-timbre reference for {speaker}.")
        retention.append(f"<Audio {index}>: reference - use its speaker timbre and vocal identity to deliver the new dialogue written for {character}.")
        line = f"Use the voice timbre from <Audio {index}> for the dialogue assigned to {speaker}."
        description = " ".join(reference.get("voice_description", "").split())
        if description:
            line += " Additional voice direction: " + description
        bindings.append(line)
    role_direction = (
        "Begin from <Picture 1>. " + ("End on <Picture 2>. " if end_frame else "")
        + "Use each reference only for the role assigned above. The spoken words are the new dialogue in the scene description. "
        "Keep the original language and existing speaker identifiers. The sample's original words and background sounds are not dialogue or ambience for this scene. "
        "If a speaking character is already visible, align their delivery and mouth movements with their speech. "
        "Otherwise keep that voice offscreen and preserve the visible cast. Visible listeners keep lips at rest."
    )
    summary = "[keyframe completion + audio reference] Generate the described scene with its supplied visual anchors and each character's referenced voice for the new dialogue."
    if fields.get("summary", "").strip():
        summary += "\n" + fields["summary"].strip()
    return "\n\n".join((
        "subject_definitions:\n" + "\n".join(item for item in definitions if item),
        "summary:\n" + summary,
        "retention_analysis:\n" + "\n".join(item for item in retention if item),
        "detailed_description:\n" + body.strip() + "\n\n" + "\n".join(bindings) + "\n" + role_direction,
        "overall_soundscape:\n" + fields.get("overall_soundscape", "Follow the ambience and physical sounds described in the scene.").strip(),
        "non_diegetic_music:\n" + fields.get("non_diegetic_music", "N/A.").strip(),
    ))


def _autogrow_accepts(inputs, group, prefix, kind, count):
    # /object_info exposes the V3 template, not its dotted live inputs. Accept a
    # future expanded representation too, but require all sockets we will use.
    if all(isinstance(inputs.get(f"{group}.{prefix}{i}"), list) and inputs[f"{group}.{prefix}{i}"][:1] == [kind] for i in range(count)):
        return True
    spec = inputs.get(group)
    if not isinstance(spec, list) or len(spec) < 2 or spec[0] != "COMFY_AUTOGROW_V3" or not isinstance(spec[1], dict):
        return False
    template = spec[1].get("template")
    if not isinstance(template, dict) or template.get("prefix") != prefix or template.get("min") != 0:
        return False
    maximum = template.get("max")
    nested = template.get("input")
    if type(maximum) is not int or maximum < count or not isinstance(nested, dict):
        return False
    required, optional = nested.get("required", {}), nested.get("optional", {})
    if not isinstance(required, dict) or not isinstance(optional, dict):
        return False
    values = list(required.values()) + list(optional.values())
    return len(values) == 1 and isinstance(values[0], list) and values[0][:1] == [kind]


def validate_voice_node_info(object_info):
    error = VoiceWorkflowError("ComfyUI no ofrece MiniMaxH3ReferenceToVideo con referencias de voz compatibles. Actualiza el kit remoto y comprueba la conexión.")
    node = object_info.get("MiniMaxH3ReferenceToVideo") if isinstance(object_info, dict) else None
    if not isinstance(node, dict) or node.get("output") != ["CONDITIONING", "LATENT"]:
        raise error
    inputs = node.get("input")
    if not isinstance(inputs, dict):
        raise error
    required, optional = inputs.get("required", {}), inputs.get("optional", {})
    if not isinstance(required, dict) or not isinstance(optional, dict):
        raise error
    fields = {"clip": "CLIP", "vae": "VAE", "audio_vae": "VAE", "prompt": "STRING", "width": "INT", "height": "INT", "length": "INT"}
    available = {**optional, **required}
    if set(required) - (set(fields) | {"ref_image_size"}):
        raise error
    for key, kind in fields.items():
        if not isinstance(available.get(key), list) or available[key][:1] != [kind]:
            raise error
    sizing = available.get("ref_image_size")
    options = None
    if isinstance(sizing, list) and sizing:
        if isinstance(sizing[0], list):
            options = sizing[0]
        elif sizing[0] == "COMBO" and len(sizing) > 1 and isinstance(sizing[1], dict):
            options = sizing[1].get("options")
    if not isinstance(options, list) or "match" not in options:
        raise error
    if not _autogrow_accepts(available, "ref_audios", "ref_audio_", "AUDIO", MAX_VOICES) or not _autogrow_accepts(available, "ref_images", "ref_image_", "IMAGE", 2):
        raise error


def prepare_voice_graph(graph, prompt, duration, seed, start, end, job_id, references, names):
    validate_voice_workflow(graph)
    validate_voice_references(references)
    if not references or len(names) != len(references) or any(not isinstance(name, str) or not name for name in names):
        raise VoiceWorkflowError("Falta subir una muestra de las voces seleccionadas.")
    result = copy.deepcopy(graph)
    result["1"]["inputs"]["image"] = start
    if end:
        result["30"]["inputs"]["image"] = end
    else:
        result["9"]["inputs"].pop("ref_images.ref_image_1")
        result.pop("30")
        result.pop(END_GUIDE)
        result["15"]["inputs"]["conditioning"] = [START_GUIDE, 0]
    for index, name in enumerate(names):
        node_id = f"fruti_voice_audio_{index}"
        if node_id in result:
            raise VoiceWorkflowError("El flujo usa un ID reservado para las muestras de voz.")
        result[node_id] = {"class_type": "LoadAudio", "inputs": {"audio": name}}
        result["9"]["inputs"][f"ref_audios.ref_audio_{index}"] = [node_id, 0]
    result["9"]["inputs"]["prompt"] = prompt
    result["12"]["inputs"]["noise_seed"] = seed
    result["28"]["inputs"]["value"] = duration
    result["20"]["inputs"]["filename_prefix"] = "FRUTINOVELAS/" + job_id
    return result
