"""Subida y lectura de imágenes y audio gestionados, siempre por ID."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from frutinovelas.config import get_settings
from frutinovelas.db import get_session
from frutinovelas.models import Asset
from frutinovelas.schemas import AssetOut, ErrorOut
from frutinovelas.services.assets import AssetError, asset_path, store_image, thumbnail_path
from frutinovelas.services.audio import store_audio
from frutinovelas.services.scenes import audit

router = APIRouter(tags=["archivos"])
CACHE = {"Cache-Control": "private, max-age=31536000, immutable"}


def _asset_or_404(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archivo no encontrado.")
    return asset


@router.post("/assets", response_model=AssetOut, status_code=201, responses={422: {"model": ErrorOut}})
def upload_asset(file: UploadFile = File(...), session: Session = Depends(get_session)):
    settings = get_settings()
    try:
        asset = store_image(session, settings, file.file, file.filename or "imagen")
    except AssetError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    audit(session, "asset.stored", "asset", asset.id, sha256=asset.sha256)
    session.commit()
    return AssetOut.model_validate(asset)


@router.post("/assets/audio", response_model=AssetOut, status_code=201, responses={422: {"model": ErrorOut}})
def upload_audio(file: UploadFile = File(...), session: Session = Depends(get_session)):
    try:
        asset = store_audio(session, get_settings(), file.file, file.filename or "audio")
    except AssetError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    audit(session, "audio.stored", "asset", asset.id, sha256=asset.sha256)
    session.commit()
    return AssetOut.model_validate(asset)


@router.get("/assets/{asset_id}", response_model=AssetOut, responses={404: {"model": ErrorOut}})
def get_asset(asset_id: str, session: Session = Depends(get_session)):
    return AssetOut.model_validate(_asset_or_404(session, asset_id))


@router.get("/assets/{asset_id}/content", responses={404: {"model": ErrorOut}})
def asset_content(asset_id: str, session: Session = Depends(get_session)):
    asset = _asset_or_404(session, asset_id)
    path = asset_path(get_settings(), asset)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El archivo falta en el almacenamiento.")
    return FileResponse(path, media_type=asset.mime, headers=CACHE)


@router.get("/assets/{asset_id}/thumb", responses={404: {"model": ErrorOut}})
def asset_thumb(asset_id: str, size: int = Query(320, ge=64, le=1024), session: Session = Depends(get_session)):
    asset = _asset_or_404(session, asset_id)
    try:
        path = thumbnail_path(get_settings(), asset, size)
    except (OSError, AssetError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No se pudo generar la miniatura.") from exc
    return FileResponse(path, media_type="image/webp", headers=CACHE)
