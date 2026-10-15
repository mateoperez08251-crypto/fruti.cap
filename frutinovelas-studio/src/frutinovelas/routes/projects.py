"""Proyectos y capítulos."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from frutinovelas.db import get_session
from frutinovelas.models import Chapter, Project, Scene, SceneRevision
from frutinovelas.schemas import (
    ChapterCreate,
    ChapterOut,
    ChapterUpdate,
    ErrorOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from frutinovelas.services.scenes import audit, current_revision_join

router = APIRouter(tags=["proyectos y capítulos"])
ERRORS = {404: {"model": ErrorOut}, 409: {"model": ErrorOut}}
# Match Python str.strip(), including non-ASCII spaces used in pasted prompts.
PROMPT_WHITESPACE = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


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
        select(func.count())
        .select_from(Chapter)
        .where(Chapter.project_id == p.id, Chapter.archived.is_(False))
    )
    return ProjectOut.model_validate(p).model_copy(update={"chapter_count": count or 0})


def _chapter_out(session: Session, c: Chapter) -> ChapterOut:
    counts = _chapter_counts().where(Scene.chapter_id == c.id)
    count, ready = session.execute(counts).one()
    return ChapterOut.model_validate(c).model_copy(update={"scene_count": count, "ready_count": ready or 0})


def _chapter_counts():
    # Count in SQL without loading prompts, asset metadata or any historical revisions.
    return (
        select(
            func.count(Scene.id).label("scene_count"),
            func.sum(
                case(
                    (
                        SceneRevision.start_asset_id.is_not(None)
                        & (func.trim(SceneRevision.prompt, PROMPT_WHITESPACE) != ""),
                        1,
                    ),
                    else_=0,
                )
            ).label("ready_count"),
        )
        .select_from(Scene)
        .outerjoin(SceneRevision, current_revision_join())
    )


# --------------------------------------------------------------------------- proyectos


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(archived: bool = Query(False), session: Session = Depends(get_session)):
    counts = (
        select(Chapter.project_id, func.count().label("count"))
        .where(Chapter.archived.is_(False))
        .group_by(Chapter.project_id)
        .subquery()
    )
    rows = session.execute(
        select(Project, func.coalesce(counts.c.count, 0))
        .outerjoin(counts, counts.c.project_id == Project.id)
        .where(Project.archived.is_(archived))
        .order_by(Project.updated_at.desc())
    )
    return [ProjectOut.model_validate(p).model_copy(update={"chapter_count": count}) for p, count in rows]


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
    counts = (
        _chapter_counts()
        .add_columns(Scene.chapter_id)
        .where(Scene.chapter_id.in_(select(Chapter.id).where(Chapter.project_id == project_id)))
        .group_by(Scene.chapter_id)
        .subquery()
    )
    rows = session.execute(
        select(Chapter, func.coalesce(counts.c.scene_count, 0), func.coalesce(counts.c.ready_count, 0))
        .outerjoin(counts, counts.c.chapter_id == Chapter.id)
        .where(Chapter.project_id == project_id, Chapter.archived.is_(archived))
        .order_by(Chapter.order_index)
    )
    return [
        ChapterOut.model_validate(c).model_copy(update={"scene_count": count, "ready_count": ready})
        for c, count, ready in rows
    ]


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
