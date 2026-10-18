"""Gateway nativo autenticado, flujos H3 y credenciales locales cifradas."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet

from frutinovelas.config import get_settings
from frutinovelas.services.audio_workflow import (
    AudioWorkflowError,
    add_audio_guides,
    validate_audio_graph,
    validate_audio_node_info,
)
from frutinovelas.services.voice_workflow import (
    VOICE_UNET,
    VOICE_UNET_SHA256,
    VOICE_WORKFLOW,
    VoiceWorkflowError,
    validate_voice_node_info,
    validate_voice_workflow,
)

WORKFLOW = "H3_USUARIO_INICIO_FINAL.api.json"


class ComfyError(ValueError):
    """Mensaje apto para la UI, sin cabeceras ni tokens."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def validate_url(url: str) -> str:
    value = url.strip().rstrip("/")
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ComfyError("Usa la URL base del gateway, sin credenciales ni parámetros.")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        raise ComfyError("La conexión remota requiere HTTPS.")
    return value


def cipher() -> Fernet:
    path = get_settings().resolved_data_dir / "comfy_credentials.key"
    if not path.exists():
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
        except FileExistsError:
            pass
    return Fernet(path.read_bytes())


def identity_key(identity: dict) -> str:
    # Older kits omit session_id. Missing history is always reconciled without resending.
    stable = {k: identity.get(k) for k in ("session_id", "comfyui_commit", "modelos", "workflows")}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def validate_workflow(graph: dict):
    expected = {
        "1": "LoadImage",
        "9": "MiniMaxH3ImageToVideo",
        "12": "RandomNoise",
        "14": "BasicScheduler",
        "20": "SaveVideo",
        "28": "PrimitiveFloat",
        "30": "LoadImage",
    }
    if not isinstance(graph, dict):
        raise ComfyError("El servidor no publicó un grafo API válido.")
    for id, kind in expected.items():
        node = graph.get(id)
        if (
            not isinstance(node, dict)
            or node.get("class_type") != kind
            or not isinstance(node.get("inputs"), dict)
        ):
            raise ComfyError("El flujo H3 publicado no coincide con el perfil inicio/final del programa.")
    h3 = graph["9"]["inputs"]
    scheduler = graph["14"]["inputs"]
    if (h3.get("width"), h3.get("height")) != (576, 1024) or scheduler.get("steps") != 20:
        raise ComfyError("Se requiere el flujo equilibrado: 576×1024 y 20 pasos.")


class ComfyClient:
    def __init__(self, url: str, token: str, transport=None):
        self.url = validate_url(url)
        settings = get_settings()
        self.client = httpx.Client(
            base_url=self.url + "/",
            headers={"Authorization": "Bearer " + token} if token else {},
            timeout=httpx.Timeout(settings.comfy_request_timeout, connect=settings.comfy_connect_timeout),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self):
        self.client.close()

    def request(self, method, path, **kwargs):
        r = self.client.request(method, path.lstrip("/"), **kwargs)
        if not 200 <= r.status_code < 300:
            raise ComfyError(
                f"El gateway devolvió HTTP {r.status_code}. Revisa URL, token y el estado de RunPod.",
                r.status_code,
            )
        return r

    def get(self, path):
        try:
            result = self.request("GET", path).json()
        except ValueError as exc:
            if isinstance(exc, ComfyError):
                raise
            raise ComfyError(
                "El gateway devolvió una respuesta JSON inválida; se reintentará la consulta."
            ) from exc
        if not isinstance(result, dict):
            raise ComfyError("El gateway devolvió una respuesta inesperada; se reintentará la consulta.")
        return result

    def connect(self):
        stats = self.get("/system_stats")
        identity = self.get("/frutinovelas/identity")
        raw = self.request("GET", "/frutinovelas/workflows/" + WORKFLOW).content
        workflows = identity.get("workflows")
        expected = workflows.get(WORKFLOW) if isinstance(workflows, dict) else None
        if not expected or hashlib.sha256(raw).hexdigest() != expected:
            raise ComfyError("El SHA-256 del flujo no coincide con la identidad del servidor.")
        graph = json.loads(raw)
        validate_workflow(graph)
        return stats, identity, graph

    def upload(self, path):
        with path.open("rb") as f:
            data = self.request(
                "POST",
                "/upload/image",
                files={"image": (path.name, f, "image/png")},
                data={"type": "input", "overwrite": "true"},
            ).json()
        return ((data.get("subfolder") + "/") if data.get("subfolder") else "") + data["name"]

    def load_voice_workflow(self, saved_identity):
        """Read the published Ref2VA graph with the existing connection identity."""
        identity = self.get("/frutinovelas/identity")
        if identity_key(identity) != identity_key(saved_identity):
            raise ComfyError("La conexión guardada cambió. Usa Guardar y comprobar antes de generar con voces.")
        workflows = identity.get("workflows")
        expected = workflows.get(VOICE_WORKFLOW) if isinstance(workflows, dict) else None
        if not expected:
            raise ComfyError(f"El servidor no publica {VOICE_WORKFLOW}. Activa el perfil de voces Ref2VA en el kit remoto.")
        models = identity.get("modelos")
        if not isinstance(models, dict) or not any(
            isinstance(model, dict) and model.get("archivo") == VOICE_UNET and model.get("sha256") == VOICE_UNET_SHA256
            for model in models.values()
        ):
            raise ComfyError("La identidad del servidor no confirma los pesos Ref2VA de voces. Actualiza el kit y comprueba la conexión.")
        raw = self.request("GET", "/frutinovelas/workflows/" + VOICE_WORKFLOW).content
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ComfyError("No coincide el SHA-256 del flujo de voces con la identidad del servidor.")
        try:
            graph = json.loads(raw)
        except ValueError as exc:
            raise ComfyError("El servidor no publicó un JSON válido para el flujo de voces.") from exc
        validate_voice_workflow(graph)
        return identity, graph

    def check_voice_support(self, graph):
        validate_voice_workflow(graph)
        for class_type in ("LoadAudio", "MiniMaxH3AddGuide", "MiniMaxH3ReferenceToVideo"):
            try:
                response = self.request("GET", "/object_info/" + class_type)
                info = response.json()
            except ComfyError as exc:
                if exc.status_code in (400, 404, 422):
                    raise VoiceWorkflowError(f"El servidor no ofrece {class_type}. Actualiza el kit remoto y comprueba la conexión.") from exc
                raise
            except ValueError as exc:
                raise VoiceWorkflowError(f"ComfyUI devolvió un esquema inválido para {class_type}. No se envió la generación.") from exc
            if class_type == "MiniMaxH3ReferenceToVideo":
                validate_voice_node_info(info)
            else:
                validate_audio_node_info(class_type, info)
                if class_type == "MiniMaxH3AddGuide":
                    inputs = info[class_type]["input"]
                    fields = {**inputs.get("optional", {}), **inputs.get("required", {})}
                    if any(not isinstance(fields.get(name), list) or fields[name][:1] != [kind] for name, kind in (("vae", "VAE"), ("image", "IMAGE"))):
                        raise VoiceWorkflowError("MiniMaxH3AddGuide no admite las anclas visuales del flujo de voces.")

    def check_audio_support(self, graph):
        validate_audio_graph(graph)
        for class_type in ("LoadAudio", "MiniMaxH3AddGuide"):
            try:
                info = self.get("/object_info/" + class_type)
            except ComfyError as exc:
                if exc.status_code in (400, 404, 422):
                    raise AudioWorkflowError(
                        f"El servidor no ofrece {class_type}. Actualiza el kit remoto y comprueba la conexión. "
                        "No se ha enviado la generación."
                    ) from exc
                raise
            validate_audio_node_info(class_type, info)

    def upload_audio(self, path, filename):
        # ComfyUI uses /upload/image and the multipart field `image` for audio
        # too. The gateway already permits this authenticated native route.
        with path.open("rb") as stream:
            response = self.request(
                "POST",
                "/upload/image",
                files={"image": (filename, stream, "audio/wav")},
                data={"type": "input", "overwrite": "true"},
            )
        try:
            data = response.json()
            name = data.get("name") if isinstance(data, dict) else None
            folder = data.get("subfolder", "") if isinstance(data, dict) else None
            if not isinstance(name, str) or not name or not isinstance(folder, str):
                raise ValueError("invalid upload response")
        except ValueError as exc:
            raise AudioWorkflowError("ComfyUI no confirmó el archivo de audio subido. No se envió la generación.") from exc
        return (folder + "/" if folder else "") + name


def prepare_graph(graph, prompt, duration, seed, start, end, job_id, *, audio_guides=None, audio_names=None):
    validate_workflow(graph)
    g = copy.deepcopy(graph)
    g["1"]["inputs"]["image"] = start
    if end:
        g["30"]["inputs"]["image"] = end
    else:
        g["9"]["inputs"].pop("last_frame", None)
        g.pop("30", None)
    g["9"]["inputs"]["prompt"] = prompt
    g["12"]["inputs"]["noise_seed"] = seed
    g["28"]["inputs"]["value"] = duration
    g["20"]["inputs"]["filename_prefix"] = "FRUTINOVELAS/" + job_id
    add_audio_guides(g, [] if audio_guides is None else audio_guides, [] if audio_names is None else audio_names, duration)
    return g
