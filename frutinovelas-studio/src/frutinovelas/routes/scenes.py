"""Escenas, sus revisiones y su orden."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from frutinovelas.db import get_session
from frutinovelas.models import Chapter
from frutinovelas.schemas import (
    ErrorOut,
    SceneCreate,
    SceneOrder,
    SceneOut,
    SceneRevisionOut,
    SceneUpdate,
)
from frutinovelas.services import scenes as svc

router = APIRouter(tags=["escenas"])
ERRORS = {404: {"model": ErrorOut}, 409: {"model": ErrorOut}, 422: {"model": ErrorOut}}


def _chapter_or_404(session: Session, chapter_id: str) -> Chapter:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Capítulo no encontrado.")
    return chapter


def _fresh(session: Session, scene_id: str) -> SceneOut:
    session.expunge_all()
    return svc.to_out(svc.load_scene(session, scene_id))


def _scene(session: Session, scene_id: str):
    try:
        return svc.load_scene(session, scene_id)
    except svc.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, svc.Invalid):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    raise exc


@router.get("/chapters/{chapter_id}/scenes", response_model=list[SceneOut], responses=ERRORS)
def list_scenes(chapter_id: str, session: Session = Depends(get_session)):
    _chapter_or_404(session, chapter_id)
    return [svc.to_out(s) for s in svc.list_scenes(session, chapter_id)]


@router.post("/chapters/{chapter_id}/scenes", response_model=SceneOut, status_code=201, responses=ERRORS)
def create_scene(chapter_id: str, data: SceneCreate, session: Session = Depends(get_session)):
    chapter = _chapter_or_404(session, chapter_id)
    try:
        scene = svc.create_scene(session, chapter, data)
    except (svc.Invalid, svc.Conflict) as exc:
        session.rollback()
        raise _handle(exc) from exc
    session.commit()
    return _fresh(session, scene.id)


@router.put("/chapters/{chapter_id}/scene-order", response_model=list[SceneOut], responses=ERRORS)
def reorder(chapter_id: str, data: SceneOrder, session: Session = Depends(get_session)):
    chapter = _chapter_or_404(session, chapter_id)
    try:
        svc.reorder_scenes(session, chapter, data.scene_ids)
    except svc.Invalid as exc:
        session.rollback()
        raise _handle(exc) from exc
    session.commit()
    session.expunge_all()
    return [svc.to_out(s) for s in svc.list_scenes(session, chapter_id)]


@router.get("/scenes/{scene_id}", response_model=SceneOut, responses=ERRORS)
def get_scene(scene_id: str, session: Session = Depends(get_session)):
    return svc.to_out(_scene(session, scene_id))


@router.patch("/scenes/{scene_id}", response_model=SceneOut, responses=ERRORS)
def update_scene(scene_id: str, data: SceneUpdate, session: Session = Depends(get_session)):
    scene = _scene(session, scene_id)
    try:
        svc.update_scene(session, scene, data)
    except (svc.Invalid, svc.Conflict) as exc:
        session.rollback()
        raise _handle(exc) from exc
    session.commit()
    return _fresh(session, scene_id)


@router.post("/scenes/{scene_id}/duplicate", response_model=SceneOut, status_code=201, responses=ERRORS)
def duplicate_scene(scene_id: str, session: Session = Depends(get_session)):
    copy = svc.duplicate_scene(session, _scene(session, scene_id))
    session.commit()
    return _fresh(session, copy.id)


@router.delete("/scenes/{scene_id}", status_code=204, responses=ERRORS)
def delete_scene(scene_id: str, session: Session = Depends(get_session)):
    svc.delete_scene(session, _scene(session, scene_id))
    session.commit()


@router.get("/scenes/{scene_id}/revisions", response_model=list[SceneRevisionOut], responses=ERRORS)
def list_revisions(scene_id: str, session: Session = Depends(get_session)):
    scene = _scene(session, scene_id)
    return [SceneRevisionOut.model_validate(r) for r in reversed(scene.revisions)]
