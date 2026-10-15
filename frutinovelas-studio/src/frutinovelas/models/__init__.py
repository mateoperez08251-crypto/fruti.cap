"""Modelo de datos de FRUTINOVELAS Studio (fase 1: proyectos, capítulos, escenas y assets).

Reglas:
- Los UUID no cambian al reordenar.
- Editar prompt, referencias, duración o parámetros crea una ``SceneRevision`` nueva;
  las anteriores se conservan intactas.
- ``revision`` (en Chapter y Scene) es un contador de control de concurrencia
  optimista: la API exige ``expected_revision`` y responde 409 ante conflictos.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(16), default="es")
    aspect_ratio: Mapped[str] = mapped_column(String(16), default="9:16")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Chapter.order_index"
    )


class Chapter(TimestampMixin, Base):
    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    script_md: Mapped[str] = mapped_column(Text, default="")
    continuity_md: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    # Compare the revision in the UPDATE itself, not only in the HTTP handler.
    # Otherwise simultaneous editors can both pass the same expected_revision.
    __mapper_args__ = {"version_id_col": revision, "version_id_generator": False}

    project: Mapped[Project] = relationship(back_populates="chapters")
    scenes: Mapped[list[Scene]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="Scene.order_index"
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16), default="image")
    # Ruta relativa al directorio de datos; nunca una ruta suministrada por el cliente.
    rel_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime: Mapped[str] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_name: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Scene(TimestampMixin, Base):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    external_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)

    __mapper_args__ = {"version_id_col": revision, "version_id_generator": False}

    chapter: Mapped[Chapter] = relationship(back_populates="scenes")
    revisions: Mapped[list[SceneRevision]] = relationship(
        back_populates="scene", cascade="all, delete-orphan", order_by="SceneRevision.number"
    )

    @property
    def current(self) -> SceneRevision | None:
        return self.revisions[-1] if self.revisions else None


class SceneRevision(Base):
    __tablename__ = "scene_revisions"
    __table_args__ = (UniqueConstraint("scene_id", "number", name="uq_scene_revision_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(Text, default="")
    start_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    end_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=5.0)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    workflow_profile_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author: Mapped[str] = mapped_column(String(16), default="ui")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scene: Mapped[Scene] = relationship(back_populates="revisions")
    start_asset: Mapped[Asset | None] = relationship(foreign_keys=[start_asset_id])
    end_asset: Mapped[Asset | None] = relationship(foreign_keys=[end_asset_id])


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(16), default="ui")
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComfyConnection(TimestampMixin, Base):
    __tablename__ = "comfy_connections"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="default")
    url: Mapped[str] = mapped_column(String(500))
    encrypted_token: Mapped[str] = mapped_column(Text)
    identity: Mapped[dict[str, Any]] = mapped_column(JSON)
    workflow: Mapped[dict[str, Any]] = mapped_column(JSON)


class GenerationJob(TimestampMixin, Base):
    __tablename__ = "generation_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    # NULL for finished jobs, unique scene ID for active ones: prevents double clicks.
    active_scene_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    state: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    prompt_id: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    encrypted_token: Mapped[str] = mapped_column(Text)
    error: Mapped[str] = mapped_column(Text, default="")
    result_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
