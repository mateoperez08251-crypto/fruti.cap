"""Proyectos y capítulos."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from frutinovelas.db import get_session
from frutinovelas.models import Chapter, Project, Scene
from frutinovelas.schemas import (
    ChapterCreate,
    ChapterOut,
    ChapterUpdate,
    ErrorOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from frutinovelas.services.scenes import audit, list_scenes, scene_status

router = APIRouter(tags=["proyectos y capítulos"])
ERRORS = {404: {"model": ErrorOut}, 409: {"model": ErrorOut}}


def _project_or_404(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proyecto no encontrado.")
    return project


def _chapter_or_404(session: Session, chapter_id: str) -> Chapter:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Capítulo no encontrado.")
    return chapter


def _project_out(session: Session, p: Project) -> ProjectOut:
    count = session.scalar(
        select(func.count()).select_from(Chapter).where(Chapter.project_id == p.id, Chapter.archived.is_(False))
    )
    return ProjectOut.model_validate(p).model_copy(update={"chapter_count": count or 0})


def _chapter_out(session: Session, c: Chapter) -> ChapterOut:
    scenes = list_scenes(session, c.id)
    ready = sum(1 for s in scenes if scene_status(s.current) == "lista")
    return ChapterOut.model_validate(c).model_copy(update={"scene_count": len(scenes), "ready_count": ready})


# --------------------------------------------------------------------------- proyectos


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(archived: bool = Query(False), session: Session = Depends(get_session)):
    rows = session.scalars(
        select(Project).where(Project.archived.is_(archived)).order_by(Project.updated_at.desc())
    )
    return [_project_out(session, p) for p in rows]


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(data: ProjectCreate, session: Session = Depends(get_session)):
    project = Project(name=data.name.strip(), language=data.language, aspect_ratio=data.aspect_ratio)
    session.add(project)
    session.flush()
    audit(session, "project.created", "project", project.id)
    session.commit()
    return _project_out(session, project)


@router.get("/projects/{project_id}", response_model=ProjectOut, responses=ERRORS)
def get_project(project_id: str, session: Session = Depends(get_session)):
    return _project_out(session, _project_or_404(session, project_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut, responses=ERRORS)
def update_project(project_id: str, data: ProjectUpdate, session: Session = Depends(get_session)):
    project = _project_or_404(session, project_id)
    for field in data.model_fields_set:
        value = getattr(data, field)
        if value is not None:
            setattr(project, field, value.strip() if isinstance(value, str) else value)
    audit(session, "project.updated", "project", project.id, fields=sorted(data.model_fields_set))
    session.commit()
    return _project_out(session, project)


# --------------------------------------------------------------------------- capítulos


@router.get("/projects/{project_id}/chapters", response_model=list[ChapterOut], responses=ERRORS)
def list_chapters(project_id: str, archived: bool = Query(False), session: Session = Depends(get_session)):
    _project_or_404(session, project_id)
    rows = session.scalars(
        select(Chapter)
        .where(Chapter.project_id == project_id, Chapter.archived.is_(archived))
        .order_by(Chapter.order_index)
    )
    return [_chapter_out(session, c) for c in rows]


@router.post("/projects/{project_id}/chapters", response_model=ChapterOut, status_code=201, responses=ERRORS)
def create_chapter(project_id: str, data: ChapterCreate, session: Session = Depends(get_session)):
    project = _project_or_404(session, project_id)
    max_order = session.scalar(select(func.max(Chapter.order_index)).where(Chapter.project_id == project.id))
    chapter = Chapter(
        project_id=project.id,
        title=data.title.strip(),
        order_index=(max_order or 0) + 1,
        script_md=data.script_md,
        continuity_md=data.continuity_md,
    )
    session.add(chapter)
    session.flush()
    audit(session, "chapter.created", "chapter", chapter.id)
    session.commit()
    return _chapter_out(session, chapter)


@router.get("/chapters/{chapter_id}", response_model=ChapterOut, responses=ERRORS)
def get_chapter(chapter_id: str, session: Session = Depends(get_session)):
    return _chapter_out(session, _chapter_or_404(session, chapter_id))


@router.patch("/chapters/{chapter_id}", response_model=ChapterOut, responses=ERRORS)
def update_chapter(chapter_id: str, data: ChapterUpdate, session: Session = Depends(get_session)):
    chapter = _chapter_or_404(session, chapter_id)
    if data.expected_revision != chapter.revision:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"El capítulo cambió mientras lo editabas (revisión actual {chapter.revision}). Recarga y vuelve a intentarlo.",
        )
    sent = data.model_fields_set - {"expected_revision"}
    for field in sent:
        value = getattr(data, field)
        if value is not None:
            setattr(chapter, field, value.strip() if field == "title" else value)
    chapter.revision += 1
    audit(session, "chapter.updated", "chapter", chapter.id, fields=sorted(sent))
    session.commit()
    return _chapter_out(session, chapter)


@router.delete("/chapters/{chapter_id}", status_code=204, responses=ERRORS)
def delete_chapter(chapter_id: str, session: Session = Depends(get_session)):
    chapter = _chapter_or_404(session, chapter_id)
    count = session.scalar(select(func.count()).select_from(Scene).where(Scene.chapter_id == chapter.id))
    if count:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El capítulo tiene escenas. Archívalo en lugar de borrarlo, o elimina primero sus escenas.",
        )
    audit(session, "chapter.deleted", "chapter", chapter.id, title=chapter.title)
    session.delete(chapter)
    session.commit()
