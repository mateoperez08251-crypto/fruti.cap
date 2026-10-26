"""Optional encrypted montage-only connection, independent of ComfyUI."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from frutinovelas.config import get_settings
from frutinovelas.services.comfy import ComfyClient, ComfyError, cipher, validate_url


class NarrationConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    token: str = Field(min_length=24, max_length=8192, repr=False)
    runtime_id: UUID

    @model_validator(mode="after")
    def validate_endpoint(self):
        self.url = validate_url(self.url)
        return self


def configuration_path():
    return get_settings().resolved_data_dir / "narrated-renderer.credential"


def load_connection() -> NarrationConnection | None:
    path = configuration_path()
    if not path.is_file():
        return None
    try:
        return NarrationConnection.model_validate_json(cipher().decrypt(path.read_bytes()))
    except Exception as exc:
        raise ComfyError("No se puede leer la conexión del montador. Vuelve a guardarla desde Videos narrados.") from exc


def save_connection(connection: NarrationConnection):
    destination = configuration_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    encrypted = cipher().encrypt(connection.model_dump_json().encode())
    descriptor, name = tempfile.mkstemp(prefix="narration-", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encrypted)
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def check_connection(url: str, token: str):
    # Validate before sending credentials or mutating the saved connection.
    candidate = NarrationConnection(url=url, token=token, runtime_id=UUID(int=0))
    client = ComfyClient(candidate.url, candidate.token)
    try:
        capabilities = client.get("/frutinovelas/narration/capabilities")
        if not capabilities.get("supported") or not capabilities.get("ffmpeg") or not capabilities.get("uploaded_video"):
            raise ComfyError("El servidor no ofrece montaje de imágenes y clips con FFmpeg. Actualiza la libreta de montaje.")
        try:
            runtime_id = UUID(capabilities["runtime_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ComfyError("El servidor no publicó una identidad válida; no se guardó la conexión.") from exc
        connection = NarrationConnection(url=url, token=token, runtime_id=runtime_id)
        save_connection(connection)
        return connection
    except httpx.HTTPError as exc:
        raise ComfyError("No se pudo contactar con el montador. Comprueba que Colab y su túnel sigan abiertos.") from exc
    finally:
        client.close()


def verify_runtime(client, connection: NarrationConnection):
    capabilities = client.get("/frutinovelas/narration/capabilities")
    if capabilities.get("runtime_id") != str(connection.runtime_id):
        raise ComfyError("Colab cambió de sesión. Guarda y comprueba de nuevo el montador antes de enviar o borrar archivos.")
    return capabilities
