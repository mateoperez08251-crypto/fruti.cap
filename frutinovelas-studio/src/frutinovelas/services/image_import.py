"""Import externally produced images via base64 or strictly guarded HTTPS.

No GPU invocation. The resulting bytes always go through store_image/Pillow.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import ipaddress
import re
import socket
import ssl
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from frutinovelas.config import get_settings
from frutinovelas.models import Asset, ImageImportRequest
from frutinovelas.schemas import AssetOut
from frutinovelas.services.assets import AssetError, store_image

MCP_BASE64_MAX = 4 * 1024 * 1024
HTTPS_MAX = 40 * 1024 * 1024
CHUNK = 64 * 1024
_ALLOWED = {"image/png", "image/jpeg", "image/webp"}
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")


class ImportErrorImage(ValueError):
    pass


def validate_public_url(url: str) -> tuple[str, str]:
    if len(url) > 2048 or any(ord(x) <= 32 or ord(x) == 127 for x in url):
        raise ImportErrorImage("URL HTTPS inválida.")
    try:
        parts = urlsplit(url)
        name = (parts.hostname or "").rstrip(".").lower()
        if parts.scheme != "https" or parts.username or parts.password or parts.fragment or parts.port not in (None, 443):
            raise ValueError("invalid URL")
        if not name or not _HOST.fullmatch(name) or "." not in name or name.endswith(".local") or name.endswith(".internal"):
            raise ValueError("invalid host")
        if name in {"localhost", "metadata.google.internal"}:
            raise ValueError("blocked host")
        try:
            ipaddress.ip_address(name)
            raise ValueError("literal IP not allowed")
        except ValueError as error:
            if str(error) == "literal IP not allowed":
                raise
        return name, parts.path or "/"
    except (ValueError, TypeError) as exc:
        raise ImportErrorImage("Solo se permite una URL HTTPS pública sin credenciales ni puertos personalizados.") from exc


def resolve_public_ips(host: str) -> list[str]:
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ImportErrorImage("No se pudo resolver el dominio público.") from exc
    ips = sorted({answer[4][0] for answer in answers})
    if not ips:
        raise ImportErrorImage("El dominio no tiene direcciones IP.")
    for ip in ips:
        addr = ipaddress.ip_address(ip)
        if not addr.is_global:
            raise ImportErrorImage("La URL apunta a una red interna o una dirección no pública.")
    return ips


class _PinnedHTTPS(httpx.HTTPTransport):
    """Pin TLS socket to an independently validated public IP; preserve original SNI/Host."""
    def __init__(self, host: str, ip: str):
        # httpcore supports a network backend providing pinned connection addresses,
        # without trusting DNS a second time inside the HTTP client.
        import httpcore
        class Network(httpcore.SyncBackend):
            def connect_tcp(self, requested_host, port, timeout=None, local_address=None, socket_options=None):
                if requested_host.decode("ascii").rstrip(".").lower() != host or port != 443:
                    raise OSError("Unexpected download destination")
                return super().connect_tcp(ip.encode("ascii"), port, timeout=timeout,
                                           local_address=local_address, socket_options=socket_options)
        super().__init__(verify=ssl.create_default_context(), trust_env=False, retries=0)
        self._pool._network_backend = Network()


def download_https(url: str, limit: int) -> bytes:
    host, _ = validate_public_url(url)
    ip = resolve_public_ips(host)[0]
    try:
        with httpx.Client(transport=_PinnedHTTPS(host, ip), timeout=httpx.Timeout(18.0, connect=5.0),
                          follow_redirects=False, trust_env=False, headers={"Accept": "image/png,image/jpeg,image/webp"}) as client:
            with client.stream("GET", url) as response:
                if 300 <= response.status_code < 400:
                    raise ImportErrorImage("Las redirecciones están bloqueadas. Usa la URL HTTPS final.")
                response.raise_for_status()
                declared_size = response.headers.get("content-length")
                if declared_size and int(declared_size) > limit:
                    raise ImportErrorImage("La imagen supera el límite permitido.")
                data = bytearray()
                for chunk in response.iter_bytes(CHUNK):
                    if len(data) + len(chunk) > limit:
                        raise ImportErrorImage("La descarga supera el límite permitido.")
                    data.extend(chunk)
                return bytes(data)
    except (httpx.HTTPError, OSError, ssl.SSLError) as exc:
        raise ImportErrorImage("No se pudo descargar la imagen HTTPS pública.") from exc


def import_image(session, request_id: str, filename: str, mime_type: str | None,
                 content_base64: str | None, url: str | None,
                 downloader=download_https) -> dict:
    try:
        identifier = str(UUID(request_id))
    except ValueError as exc:
        raise ImportErrorImage("request_id debe ser un UUID.") from exc
    if (content_base64 is None) == (url is None):
        raise ImportErrorImage("Indica exactamente una fuente: content_base64 o url.")
    if mime_type and mime_type.lower() not in _ALLOWED:
        raise ImportErrorImage("MIME no admitido. Usa image/png, image/jpeg o image/webp.")
    filename = filename.replace("\\", "/").split("/")[-1].strip()[:200] or "imagen"
    if not re.fullmatch(r"[\w .()\-áéíóúÁÉÍÓÚñÑ]+", filename):
        raise ImportErrorImage("El nombre del archivo contiene caracteres no admitidos.")
    if content_base64 is not None:
        if len(content_base64) > (MCP_BASE64_MAX * 4 // 3) + 8:
            raise ImportErrorImage("Base64 supera 4 MiB. Usa HTTPS o el formulario HTTP de Studio.")
        try:
            data = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImportErrorImage("Base64 inválido.") from exc
        if len(data) > MCP_BASE64_MAX:
            raise ImportErrorImage("Base64 supera 4 MiB.")
        fingerprint = hashlib.sha256(b"bytes\0" + data).hexdigest()
    else:
        validate_public_url(url)
        fingerprint = hashlib.sha256(("url\0" + url).encode()).hexdigest()
    existing = session.get(ImageImportRequest, identifier)
    if existing:
        if existing.fingerprint != fingerprint:
            raise ImportErrorImage("request_id ya corresponde a otra imagen.")
        asset = session.get(Asset, existing.asset_id)
        return {**AssetOut.model_validate(asset).model_dump(mode="json"), "created": False, "reused": True,
                "inspect_tool": "inspect_studio_image", "assignment_tool": "set_studio_scene_frame"}
    if url is not None:
        data = downloader(url, min(HTTPS_MAX, get_settings().max_upload_mb * 1024 * 1024))
    if len(data) == 0:
        raise ImportErrorImage("Imagen vacía.")
    with io.BytesIO(data) as stream:
        sha = hashlib.sha256(data).hexdigest()
        preexisting = session.scalar(select(Asset).where(Asset.sha256 == sha))
        try:
            asset = store_image(session, get_settings(), stream, filename)
        except AssetError as exc:
            raise ImportErrorImage(str(exc)) from exc
    if mime_type and asset.mime != mime_type.lower():
        raise ImportErrorImage("El MIME declarado no coincide con los bytes de la imagen.")
    created = preexisting is None
    session.add(ImageImportRequest(request_id=identifier, fingerprint=fingerprint, asset_id=asset.id,
                                   created_at=datetime.now(UTC)))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        record = session.get(ImageImportRequest, identifier)
        if not record or record.fingerprint != fingerprint:
            raise ImportErrorImage("El request_id está ocupado por otra importación.")
        asset = session.get(Asset, record.asset_id)
        created = False
    return {**AssetOut.model_validate(asset).model_dump(mode="json"), "created": created,
            "reused": not created, "inspect_tool": "inspect_studio_image",
            "assignment_tool": "set_studio_scene_frame"}
