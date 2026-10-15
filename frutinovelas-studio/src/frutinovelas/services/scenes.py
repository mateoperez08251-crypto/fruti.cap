"""Lógica de escenas: creación, revisiones, reordenación y serialización."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from frutinovelas.models import Asset, AuditEvent, Chapter, GenerationJob, Scene, SceneRevision
from frutinovelas.schemas import AssetOut, SceneCreate, SceneOut, SceneUpdate

# Campos cuya modificación crea una SceneRevision nueva.
REVISION_FIELDS = ("prompt", "duration_seconds", "start_asset_id", "end_asset_id", "parameters")


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    def __init__(self, current_revision: int):
        super().__init__(
            f"La escena cambió mientras la editabas (revisión actual {current_revision}). Recarga y vuelve a intentarlo."
        )
        self.current_revision = current_revision


class Invalid(ValueError):
    pass


class ActiveGenerationConflict(RuntimeError):
    pass


def audit(session: Session, event: str, entity_type: str, entity_id: str, actor: str = "ui", **detail: Any) -> None:
    session.add(AuditEvent(event=event, actor=actor, entity_type=entity_type, entity_id=entity_id, detail=detail))


def _check_asset(session: Session, asset_id: str | None) -> None:
    if asset_id is not None and session.get(Asset, asset_id) is None:
        raise Invalid(f"La imagen {asset_id} no existe.")


def scene_status(rev: SceneRevision | None) -> str:
    if rev is None or rev.start_asset_id is None:
        return "sin_imagen"
    if not rev.prompt.strip():
        return "sin_prompt"
    return "lista"


def to_out(scene: Scene) -> SceneOut:
    return _to_out(scene, scene.current)


def _to_out(scene: Scene, rev: SceneRevision | None) -> SceneOut:
    start = rev.start_asset if rev else None
    end = rev.end_asset if rev else None
    mode = None
    if start is not None:
        mode = "FL2VA" if end is not None else "I2VA"
    return SceneOut(
        id=scene.id,
        chapter_id=scene.chapter_id,
        order_index=scene.order_index,
        external_key=scene.external_key,
        title=scene.title,
        description=scene.description,
        revision=scene.revision,
        revision_number=rev.number if rev else 0,
        prompt=rev.prompt if rev else "",
        duration_seconds=rev.duration_seconds if rev else 5.0,
        parameters=dict(rev.parameters or {}) if rev else {},
        start_asset=AssetOut.model_validate(start) if start else None,
        end_asset=AssetOut.model_validate(end) if end else None,
        mode=mode,
        status=scene_status(rev),
        updated_at=scene.updated_at,
    )


def latest_revision_number():
    """Correlated lookup uses the existing unique (scene_id, number) index."""
    return (
        select(func.max(SceneRevision.number))
        .where(SceneRevision.scene_id == Scene.id)
        .correlate(Scene)
        .scalar_subquery()
    )


def current_revision_join():
    return and_(
        SceneRevision.scene_id == Scene.id,
        SceneRevision.number == latest_revision_number(),
    )


def list_scene_outputs(session: Session, chapter_id: str) -> list[SceneOut]:
    """List only current references/content; history is read explicitly, never replaced."""
    rows = session.execute(
        select(Scene, SceneRevision)
        .outerjoin(SceneRevision, current_revision_join())
        .where(Scene.chapter_id == chapter_id)
        .order_by(Scene.order_index)
        .options(joinedload(SceneRevision.start_asset), joinedload(SceneRevision.end_asset))
    )
    return [_to_out(scene, rev) for scene, rev in rows]


def load_scene(session: Session, scene_id: str) -> Scene:
    scene = session.scalar(
        select(Scene)
        .where(Scene.id == scene_id)
        .options(selectinload(Scene.revisions).selectinload(SceneRevision.start_asset))
        .options(selectinload(Scene.revisions).selectinload(SceneRevision.end_asset))
    )
    if scene is None:
        raise NotFound("Escena no encontrada.")
    return scene


def list_scenes(session: Session, chapter_id: str) -> list[Scene]:
    return list(
        session.scalars(
            select(Scene)
            .where(Scene.chapter_id == chapter_id)
            .order_by(Scene.order_index)
            .options(selectinload(Scene.revisions).selectinload(SceneRevision.start_asset))
            .options(selectinload(Scene.revisions).selectinload(SceneRevision.end_asset))
        )
    )


def create_scene(session: Session, chapter: Chapter, data: SceneCreate, actor: str = "ui") -> Scene:
    _check_asset(session, data.start_asset_id)
    _check_asset(session, data.end_asset_id)
    if data.end_asset_id and not data.start_asset_id:
        raise Invalid("Una imagen final requiere imagen inicial.")
    max_order = session.scalar(select(func.max(Scene.order_index)).where(Scene.chapter_id == chapter.id))
    scene = Scene(
        chapter_id=chapter.id,
        order_index=(max_order or 0) + 1,
        title=data.title or "",
        description=data.description,
        external_key=data.external_key,
    )
    scene.revisions.append(
        SceneRevision(
            number=1,
            prompt=data.prompt,
            duration_seconds=data.duration_seconds,
            start_asset_id=data.start_asset_id,
            end_asset_id=data.end_asset_id,
            parameters=data.parameters.model_dump(exclude_none=True),
            author=actor,
        )
    )
    session.add(scene)
    session.flush()
    if not scene.title:
        scene.title = f"Escena {scene.order_index}"
    audit(session, "scene.created", "scene", scene.id, actor)
    return scene


def update_scene(session: Session, scene: Scene, data: SceneUpdate, actor: str = "ui") -> Scene:
    if data.expected_revision != scene.revision:
        raise Conflict(scene.revision)
    sent = data.model_fields_set - {"expected_revision"}
    current = scene.current

    for name in ("title", "description"):
        if name in sent and getattr(data, name) is not None:
            setattr(scene, name, getattr(data, name))

    new_values: dict[str, Any] = {
        "prompt": current.prompt if current else "",
        "duration_seconds": current.duration_seconds if current else 5.0,
        "start_asset_id": current.start_asset_id if current else None,
        "end_asset_id": current.end_asset_id if current else None,
        "parameters": dict(current.parameters or {}) if current else {},
    }
    if "prompt" in sent and data.prompt is not None:
        new_values["prompt"] = data.prompt
    if "duration_seconds" in sent and data.duration_seconds is not None:
        new_values["duration_seconds"] = data.duration_seconds
    if "start_asset_id" in sent:
        _check_asset(session, data.start_asset_id)
        new_values["start_asset_id"] = data.start_asset_id
    if "end_asset_id" in sent:
        _check_asset(session, data.end_asset_id)
        new_values["end_asset_id"] = data.end_asset_id
    if "parameters" in sent and data.parameters is not None:
        new_values["parameters"] = data.parameters.model_dump(exclude_none=True)

    if new_values["end_asset_id"] and not new_values["start_asset_id"]:
        raise Invalid("Una imagen final requiere imagen inicial.")

    changed = current is None or any(new_values[f] != getattr(current, f) for f in REVISION_FIELDS)
    if changed:
        number = (current.number if current else 0) + 1
        scene.revisions.append(SceneRevision(number=number, author=actor, **new_values))
    scene.revision += 1
    session.flush()
    audit(session, "scene.updated", "scene", scene.id, actor, new_revision=changed, fields=sorted(sent))
    return scene


def duplicate_scene(session: Session, scene: Scene, actor: str = "ui") -> Scene:
    rev = scene.current
    # Desplaza las escenas posteriores para insertar la copia justo después.
    for s in session.scalars(
        select(Scene).where(Scene.chapter_id == scene.chapter_id, Scene.order_index > scene.order_index)
    ):
        s.order_index += 1
    copy = Scene(
        chapter_id=scene.chapter_id,
        order_index=scene.order_index + 1,
        title=f"{scene.title} (copia)"[:200],
        description=scene.description,
    )
    copy.revisions.append(
        SceneRevision(
            number=1,
            prompt=rev.prompt if rev else "",
            duration_seconds=rev.duration_seconds if rev else 5.0,
            start_asset_id=rev.start_asset_id if rev else None,
            end_asset_id=rev.end_asset_id if rev else None,
            parameters=dict(rev.parameters or {}) if rev else {},
            author=actor,
        )
    )
    session.add(copy)
    session.flush()
    audit(session, "scene.duplicated", "scene", copy.id, actor, source=scene.id)
    return copy


def reorder_scenes(session: Session, chapter: Chapter, scene_ids: list[str], actor: str = "ui") -> None:
    scenes = {s.id: s for s in session.scalars(select(Scene).where(Scene.chapter_id == chapter.id))}
    if len(scene_ids) != len(set(scene_ids)) or set(scene_ids) != set(scenes):
        raise Invalid("El nuevo orden debe incluir exactamente todas las escenas del capítulo.")
    for i, sid in enumerate(scene_ids, start=1):
        scenes[sid].order_index = i
    session.flush()
    audit(session, "chapter.scenes_reordered", "chapter", chapter.id, actor)


def delete_scene(session: Session, scene: Scene, actor: str = "ui") -> None:
    chapter_id = scene.chapter_id
    audit(session, "scene.deleted", "scene", scene.id, actor, title=scene.title)
    # The audit write acquires SQLite's writer lock before checking jobs, so an
    # enqueue cannot slip between the check and the cascading scene deletion.
    # The caller rolls back this audit together with a rejected deletion.
    session.flush()
    active = session.scalar(
        select(GenerationJob.id)
        .where(
            GenerationJob.scene_id == scene.id,
            or_(
                GenerationJob.active_scene_id.is_not(None),
                GenerationJob.state.not_in(("completed", "failed")),
            ),
        )
        .limit(1)
    )
    if active is not None:
        raise ActiveGenerationConflict(
            "La escena tiene una generación activa o pendiente de confirmar. "
            "Espera a que termine antes de borrarla."
        )
    session.delete(scene)
    session.flush()
    remaining = session.scalars(select(Scene).where(Scene.chapter_id == chapter_id).order_by(Scene.order_index))
    for i, s in enumerate(remaining, start=1):
        s.order_index = i
