"""Almacenamiento gestionado de imágenes de referencia.

Las imágenes se copian al directorio de datos con nombre por hash SHA-256, de modo
que borrar o mover el original no rompe el proyecto. Se valida el contenido real
con Pillow, no la extensión.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from frutinovelas.config import Settings
from frutinovelas.models import Asset

ALLOWED_FORMATS = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"), "WEBP": ("image/webp", ".webp")}
CHUNK = 1024 * 1024


class AssetError(ValueError):
    """Archivo rechazado; el mensaje es apto para mostrar al usuario."""


@dataclass
class _Probe:
    fmt: str
    width: int
    height: int


def _probe_image(path: Path, max_side: int) -> _Probe:
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:  # verify() invalida el objeto; se reabre
            fmt = (img.format or "").upper()
            width, height = img.size
            img.load()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise AssetError("El archivo no es una imagen válida o está dañado.") from exc
    except Image.DecompressionBombError as exc:
        raise AssetError("La imagen es demasiado grande para procesarla con seguridad.") from exc
    if fmt not in ALLOWED_FORMATS:
        raise AssetError(f"Formato {fmt or 'desconocido'} no admitido. Usa PNG, JPEG o WebP.")
    if width < 16 or height < 16:
        raise AssetError("La imagen es demasiado pequeña (mínimo 16×16).")
    if max(width, height) > max_side:
        raise AssetError(f"La imagen supera {max_side} px en su lado mayor.")
    return _Probe(fmt, width, height)


def store_image(session: Session, settings: Settings, stream: BinaryIO, original_name: str) -> Asset:
    """Guarda la imagen y devuelve el Asset (reutiliza uno existente si el hash coincide)."""
    limit = settings.max_upload_mb * 1024 * 1024
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = settings.tmp_dir / f"upload-{uuid.uuid4().hex}"
    digest = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as out:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise AssetError(f"La imagen supera el límite de {settings.max_upload_mb} MB.")
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise AssetError("El archivo está vacío.")

        sha = digest.hexdigest()
        existing = session.scalar(select(Asset).where(Asset.sha256 == sha))
        if existing is not None and existing.kind != "image":
            raise AssetError("El archivo no es una imagen. Usa la carga de audio para las voces.")
        if existing is not None and (settings.resolved_data_dir / existing.rel_path).is_file():
            return existing

        probe = _probe_image(tmp, settings.max_image_side)
        mime, ext = ALLOWED_FORMATS[probe.fmt]
        rel = Path("assets") / sha[:2] / f"{sha}{ext}"
        dest = settings.resolved_data_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dest)

        if existing is not None:  # registro existente cuyo archivo faltaba: se repara
            existing.rel_path = rel.as_posix()
            session.flush()
            return existing

        asset = Asset(
            kind="image",
            rel_path=rel.as_posix(),
            sha256=sha,
            size_bytes=size,
            mime=mime,
            width=probe.width,
            height=probe.height,
            original_name=Path(original_name or "imagen").name[:300],
        )
        session.add(asset)
        session.flush()
        return asset
    finally:
        tmp.unlink(missing_ok=True)


def asset_path(settings: Settings, asset: Asset) -> Path:
    base = settings.resolved_data_dir
    path = (base / asset.rel_path).resolve()
    if base not in path.parents:
        raise AssetError("Ruta de asset fuera del almacenamiento gestionado.")
    return path


def thumbnail_path(settings: Settings, asset: Asset, size: int) -> Path:
    """Miniatura WebP en caché; el original permanece intacto."""
    if asset.kind != "image":
        raise AssetError("Solo las imágenes tienen miniatura.")
    size = max(64, min(size, 1024))
    out = settings.cache_dir / "thumbs" / f"{asset.sha256}-{size}.webp"
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(f".{uuid.uuid4().hex}.tmp")
    with Image.open(asset_path(settings, asset)) as img:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if img.mode in ("P", "LA", "PA") or "A" in img.mode else "RGB")
        img.thumbnail((size, size))
        img.save(tmp, "WEBP", quality=82)
    os.replace(tmp, out)
    return out
