"""Esquemas de entrada y salida de la API v1."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MIN_DURATION = 0.5
MAX_DURATION = 60.0

SceneStatus = Literal["sin_imagen", "sin_prompt", "lista"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- proyectos


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    language: str = Field(default="es", max_length=16)
    aspect_ratio: str = Field(default="9:16", max_length=16)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    aspect_ratio: str | None = Field(default=None, max_length=16)
    archived: bool | None = None


class ProjectOut(ORM):
    id: str
    name: str
    language: str
    aspect_ratio: str
    archived: bool
    created_at: datetime
    updated_at: datetime
    chapter_count: int = 0


# --------------------------------------------------------------------------- capítulos


class ChapterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    script_md: str = ""
    continuity_md: str = ""


class ChapterUpdate(BaseModel):
    expected_revision: int
    title: str | None = Field(default=None, min_length=1, max_length=200)
    script_md: str | None = None
    continuity_md: str | None = None
    archived: bool | None = None


class ChapterOut(ORM):
    id: str
    project_id: str
    title: str
    order_index: int
    script_md: str
    continuity_md: str
    revision: int
    archived: bool
    created_at: datetime
    updated_at: datetime
    scene_count: int = 0
    ready_count: int = 0


# --------------------------------------------------------------------------- assets


class AssetOut(ORM):
    id: str
    kind: str
    sha256: str
    size_bytes: int
    mime: str
    width: int | None
    height: int | None
    duration_seconds: float | None = None
    original_name: str
    created_at: datetime


# --------------------------------------------------------------------------- escenas


class SceneAudioGuide(BaseModel):
    """Only IDs and timing come from clients; the server supplies frozen metadata."""

    model_config = ConfigDict(extra="ignore")

    asset_id: str = Field(min_length=1, max_length=36)
    character_id: str | None = Field(default=None, min_length=1, max_length=36)
    start_seconds: float = Field(default=0.0, ge=0, le=MAX_DURATION, allow_inf_nan=False)


class SceneParameters(BaseModel):
    model_config = ConfigDict(extra="allow")

    seed_mode: Literal["random", "fixed"] = "random"
    seed: int | None = Field(default=None, ge=0, le=2**64 - 1)
    character_ids: list[str] = Field(default_factory=list, max_length=2)
    image_prompt: str = Field(default="", max_length=30000)
    image_approval: Literal["manual", "automatic"] = "manual"
    audio_guides: list[SceneAudioGuide] = Field(default_factory=list, max_length=8)


class SceneCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    description: str = ""
    external_key: str | None = Field(default=None, max_length=64)
    prompt: str = ""
    duration_seconds: float = Field(default=5.0, ge=MIN_DURATION, le=MAX_DURATION, allow_inf_nan=False)
    start_asset_id: str | None = None
    end_asset_id: str | None = None
    parameters: SceneParameters = Field(default_factory=SceneParameters)


class SceneUpdate(BaseModel):
    """Solo se modifican los campos enviados. Enviar ``end_asset_id: null`` quita el final."""

    expected_revision: int
    title: str | None = Field(default=None, max_length=200)
    description: str | None = None
    prompt: str | None = None
    duration_seconds: float | None = Field(default=None, ge=MIN_DURATION, le=MAX_DURATION, allow_inf_nan=False)
    start_asset_id: str | None = None
    end_asset_id: str | None = None
    parameters: SceneParameters | None = None


class SceneOrder(BaseModel):
    scene_ids: list[str] = Field(min_length=0)


class SceneRevisionOut(ORM):
    id: str
    number: int
    prompt: str
    start_asset_id: str | None
    end_asset_id: str | None
    duration_seconds: float
    parameters: dict[str, Any]
    author: str
    created_at: datetime


class SceneOut(BaseModel):
    id: str
    chapter_id: str
    order_index: int
    external_key: str | None
    title: str
    description: str
    revision: int
    revision_number: int
    prompt: str
    duration_seconds: float
    parameters: dict[str, Any]
    start_asset: AssetOut | None
    end_asset: AssetOut | None
    mode: Literal["I2VA", "FL2VA"] | None
    status: SceneStatus
    updated_at: datetime


# --------------------------------------------------------------------------- sistema


class ComfyStatus(BaseModel):
    url: str
    reachable: bool
    version: str | None = None
    detail: str | None = None


class StorageStatus(BaseModel):
    data_dir: str
    free_bytes: int
    low_space: bool


class SystemStatus(BaseModel):
    app_version: str
    comfyui: ComfyStatus
    storage: StorageStatus
    ffmpeg: bool


class ErrorOut(BaseModel):
    detail: str
