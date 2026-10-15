"""Estado del sistema para la barra inferior de la interfaz (sin secretos)."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import time

import httpx
from fastapi import APIRouter

from frutinovelas import __version__
from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.doctor import MIN_FREE_GB, mask_url
from frutinovelas.models import ComfyConnection
from frutinovelas.schemas import ComfyStatus, StorageStatus, SystemStatus
from frutinovelas.services.generation import connection_token

router = APIRouter(tags=["sistema"])

_comfy_cache: tuple[float, tuple[str, str], ComfyStatus] | None = None
_COMFY_TTL = 5.0


async def _comfy_status(url: str, token: str | None = None) -> ComfyStatus:
    global _comfy_cache
    now = time.monotonic()
    cache_key = (url, hashlib.sha256((token or "").encode()).hexdigest())
    if _comfy_cache and _comfy_cache[1] == cache_key and now - _comfy_cache[0] < _COMFY_TTL:
        return _comfy_cache[2]
    shown = mask_url(url)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.5, connect=2.0), trust_env=False) as client:
            resp = await client.get(
                url.rstrip("/") + "/system_stats",
                headers={"Authorization": "Bearer " + token} if token else {},
            )
        if resp.status_code == 200:
            version = (resp.json().get("system") or {}).get("comfyui_version")
            result = ComfyStatus(url=shown, reachable=True, version=version)
        else:
            result = ComfyStatus(url=shown, reachable=False, detail=f"HTTP {resp.status_code}")
    except (httpx.HTTPError, ValueError) as exc:
        result = ComfyStatus(url=shown, reachable=False, detail=exc.__class__.__name__)
    _comfy_cache = (now, cache_key, result)
    return result


@router.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@router.get("/system/status", response_model=SystemStatus)
async def system_status():
    s = get_settings()
    with session_factory()() as session:
        connection = session.get(ComfyConnection, "default")
        url = connection.url if connection else s.comfyui_base_url
        token = connection_token(connection) if connection else s.comfyui_token
    comfy = await _comfy_status(url, token)
    usage = await asyncio.to_thread(shutil.disk_usage, s.resolved_data_dir)
    return SystemStatus(
        app_version=__version__,
        comfyui=comfy,
        storage=StorageStatus(
            data_dir=str(s.resolved_data_dir),
            free_bytes=usage.free,
            low_space=usage.free < MIN_FREE_GB * 1024**3,
        ),
        ffmpeg=shutil.which(s.ffmpeg_path) is not None,
    )
