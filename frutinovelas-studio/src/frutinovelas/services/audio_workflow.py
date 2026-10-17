"""Audio guía nativo para el flujo H3 FL2VA existente, sin cambiar sus modelos.

Contrato contrastado con ComfyUI 3541246a9c997f4b8c32f9f88f3c985d02021c79:
comfy_extras/nodes_minimax_h3.py::MiniMaxH3AddGuide. Las guías condicionan la
inferencia; el audio de salida sigue siendo generado y no equivale a un doblaje
literal ni a clonar una voz a partir de una muestra.
"""

from __future__ import annotations

import json
import math
import re

FPS = 24
MAX_AUDIO_GUIDES = 8


class AudioWorkflowError(ValueError):
    """Problema de preparación definitivo antes de enviar una inferencia."""


def guide_timing(guide):
    """Return the native anchor frame and the actual guide interval in seconds."""
    start = guide.get("start_seconds", 0)
    asset = guide.get("asset")
    duration = asset.get("duration_seconds") if isinstance(asset, dict) else None
    if (
        type(start) not in (int, float)
        or not math.isfinite(start)
        or not 0 <= start <= 15
        or type(duration) not in (int, float)
        or not math.isfinite(duration)
        or not 0 < duration <= 15
    ):
        raise AudioWorkflowError("El audio guardado no tiene una duración o un inicio válidos.")
    frame = round(start * FPS)
    return frame, frame / FPS, frame / FPS + duration


def validate_audio_guides(guides, duration):
    """Recheck frozen revision data before preparing a remote graph."""
    if not isinstance(guides, list) or len(guides) > MAX_AUDIO_GUIDES:
        raise AudioWorkflowError(f"Cada escena admite hasta {MAX_AUDIO_GUIDES} audios guía.")
    intervals = []
    for guide in guides:
        if not isinstance(guide, dict):
            raise AudioWorkflowError("La revisión contiene un audio guía no válido.")
        asset = guide.get("asset")
        if (
            not isinstance(asset, dict)
            or not isinstance(guide.get("asset_id"), str)
            or asset.get("id") != guide["asset_id"]
            or asset.get("kind") != "audio"
            or not isinstance(asset.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])
        ):
            raise AudioWorkflowError("Falta la referencia de audio original en la revisión guardada.")
        if guide.get("character_id") is not None and (
            not isinstance(guide.get("character_name"), str) or not guide["character_name"].strip()
        ):
            raise AudioWorkflowError("Falta la identidad del personaje asociado al audio guardado.")
        if not isinstance(guide.get("voice_description", ""), str):
            raise AudioWorkflowError("La descripción de voz guardada no es válida.")
        _, start, end = guide_timing(guide)
        if end > duration + 1e-6:
            raise AudioWorkflowError("Un audio guía termina después de la escena. Ajusta su inicio o duración.")
        intervals.append((start, end))
    intervals.sort()
    for previous, current in zip(intervals, intervals[1:], strict=False):
        if current[0] < previous[1] - 1e-6:
            raise AudioWorkflowError("Los audios guía de diálogo se superponen. Separa sus tiempos de inicio.")


def effective_audio_prompt(prompt, guides):
    """Add named speaker timing without rewriting the saved prompt or dialogue.

AddGuide has no reference tags or character input. Named, timed direction sends
the saved speaker association to the text conditioning as well as the waveform
to the audio conditioning. Existing (S1)/(S2) identifiers remain untouched.
"""
    if not guides:
        return prompt
    lines = ["Audio guide timing for this scene (seconds):"]
    for guide in sorted(guides, key=lambda item: guide_timing(item)[0]):
        _, start, end = guide_timing(guide)
        interval = f"{start:.3f}-{end:.3f}s"
        if guide.get("character_id") is not None:
            name = json.dumps(" ".join(guide["character_name"].split()), ensure_ascii=False)
            line = (
                f"During {interval}, the character named {name} is the speaker for the audio "
                f"anchored at {start:.3f}s. If this character is already visible in the scene, "
                "align their delivery and mouth movements with the guided speech; otherwise "
                "keep the voice offscreen and preserve the visible cast. Visible listeners keep lips at rest."
            )
            description = " ".join(guide.get("voice_description", "").split())
            if description:
                line += f" Voice direction for {name}: {description}"
        else:
            line = f"During {interval}, follow the scene audio anchored at {start:.3f}s."
        lines.append(line)
    block = "\n".join(lines)
    # Keep this direction in the description, before ambience/music fields. A
    # free-form prompt receives the same block at its end, with no reformatting.
    next_field = re.search(r"(?m)^[ \t]*(?:overall_soundscape|non_diegetic_music)[ \t]*:", prompt)
    if next_field:
        return prompt[: next_field.start()] + "\n" + block + "\n" + prompt[next_field.start() :]
    return prompt + "\n\n" + block


def validate_audio_graph(graph):
    """Require the connections which will be extended, not a guessed graph."""
    expected = {"8": "VAELoader", "15": "BasicGuider", "16": "SamplerCustomAdvanced"}
    for node_id, class_type in expected.items():
        node = graph.get(node_id)
        if (
            not isinstance(node, dict)
            or node.get("class_type") != class_type
            or not isinstance(node.get("inputs"), dict)
        ):
            raise AudioWorkflowError("El flujo H3 no contiene las conexiones necesarias para audio guía.")
    vae_name = graph["8"]["inputs"].get("vae_name")
    if (
        not isinstance(vae_name, str)
        or vae_name.replace("\\", "/").rsplit("/", 1)[-1] != "minimax_h3_audio_vae_fp32.safetensors"
        or graph["15"]["inputs"].get("conditioning") != ["9", 0]
        or graph["16"]["inputs"].get("latent_image") != ["9", 1]
    ):
        raise AudioWorkflowError("El audio VAE o los enlaces de H3 no coinciden con el flujo compatible.")


def validate_audio_node_info(class_type, object_info):
    """Validate the live native schema before any audio job can reach /prompt."""
    expected = {
        "LoadAudio": ({"audio": "COMBO"}, "AUDIO"),
        "MiniMaxH3AddGuide": (
            {"positive": "CONDITIONING", "latent": "LATENT", "audio": "AUDIO", "audio_vae": "VAE", "frame_idx": "INT"},
            "CONDITIONING",
        ),
    }
    fields, output = expected[class_type]
    error = AudioWorkflowError(
        f"ComfyUI no ofrece {class_type} con entradas de audio compatibles. "
        "Actualiza el kit remoto y vuelve a comprobar la conexión. No se ha enviado la generación."
    )
    if not isinstance(object_info, dict):
        raise error
    node = object_info.get(class_type)
    if not isinstance(node, dict) or not isinstance(node.get("output"), list) or node["output"][:1] != [output]:
        raise error
    inputs = node.get("input")
    if not isinstance(inputs, dict):
        raise error
    required, optional = inputs.get("required", {}), inputs.get("optional", {})
    if not isinstance(required, dict) or not isinstance(optional, dict) or set(required) - set(fields):
        raise error
    available = {**optional, **required}
    for name, kind in fields.items():
        spec = available.get(name)
        if not isinstance(spec, list) or not spec:
            raise error
        valid = (isinstance(spec[0], list) or spec[0] == "COMBO") if kind == "COMBO" else spec[0] == kind
        if not valid:
            raise error


def add_audio_guides(graph, guides, names, duration):
    """Mutate a job's private graph copy; model, sampling and output stay linked."""
    validate_audio_guides(guides, duration)
    if not guides:
        return
    validate_audio_graph(graph)
    if len(names) != len(guides) or any(not isinstance(name, str) or not name for name in names):
        raise AudioWorkflowError("Falta subir uno de los audios de esta escena.")
    positive = ["9", 0]
    timed_inputs = sorted(zip(guides, names, strict=True), key=lambda item: guide_timing(item[0])[0])
    for index, (guide, name) in enumerate(timed_inputs):
        audio_id, guide_id = f"fruti_audio_{index}", f"fruti_guide_{index}"
        if audio_id in graph or guide_id in graph:
            raise AudioWorkflowError("El flujo publicado ya contiene nodos de audio con nombres reservados.")
        graph[audio_id] = {"class_type": "LoadAudio", "inputs": {"audio": name}}
        graph[guide_id] = {
            "class_type": "MiniMaxH3AddGuide",
            "inputs": {
                "positive": positive,
                "latent": ["9", 1],
                "audio_vae": ["8", 0],
                "audio": [audio_id, 0],
                "frame_idx": guide_timing(guide)[0],
            },
        }
        positive = [guide_id, 0]
    graph["15"]["inputs"]["conditioning"] = positive
