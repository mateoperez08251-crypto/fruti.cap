"""Validated audio-first storyboard payloads (no speech-to-text inference)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Motion = Literal["zoom_in", "zoom_out", "pan_left", "pan_right", "still"]
Aspect = Literal["9:16", "16:9"]
MediaMode = Literal["static", "animated"]
FlowTool = Literal["standard", "storyboard_studio"]


class VisualReference(BaseModel):
    """A registered Studio image used as identity or style guide; never a path."""
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    role: Literal["identity", "style"]
    description: str = Field(default="", max_length=500)


class NarratedShot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0, le=300, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, le=300, allow_inf_nan=False)
    text: str = Field(default="", max_length=2000)
    image_prompt: str = Field(default="", max_length=30000)
    animation_prompt: str = Field(default="", max_length=30000)
    image_asset_id: str | None = Field(default=None, max_length=36)
    motion: Motion = "zoom_in"
    # Static shots animate the still with FFmpeg; animated shots use a Flow clip.
    media_mode: MediaMode = "static"
    references: list[VisualReference] = Field(default_factory=list, max_length=3)
    visual_style: str = Field(default="", max_length=4000)
    flow_tool: FlowTool = "standard"
    # Server-managed links to the Flow queue. Validated against the project on save.
    flow_scene_id: str | None = Field(default=None, max_length=36)
    flow_image_job_id: str | None = Field(default=None, max_length=36)
    flow_video_job_id: str | None = Field(default=None, max_length=36)
    # Explicit version choice; synchronisation never replaces a pinned image.
    selected_image_job_id: str | None = Field(default=None, max_length=36)
    # Legacy remote-montage clip references (ComfyUI gateway).
    clip_filename: str | None = Field(default=None, max_length=300)
    clip_subfolder: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_seconds - self.start_seconds < 0.05:
            raise ValueError("El final de una toma debe ser posterior al inicio.")
        return self


class NarratedCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    audio_asset_id: str = Field(min_length=1, max_length=36)
    transcript: str = Field(default="", max_length=100000)
    aspect_ratio: Aspect = "9:16"
    shots: list[NarratedShot] | None = Field(default=None, max_length=90)


class NarratedUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    audio_asset_id: str | None = Field(default=None, min_length=1, max_length=36)
    transcript: str | None = Field(default=None, max_length=100000)
    aspect_ratio: Aspect | None = None
    shots: list[NarratedShot] | None = Field(default=None, max_length=90)


class NarratedRenderRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    # auto: local FFmpeg when Flow clips are used or no remote renderer is configured.
    engine: Literal["auto", "local", "remote"] = "auto"


class NarratedPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    media_mode: MediaMode = "static"
    shot_count: int = Field(ge=1, le=90)
    visual_style: str = Field(default="", max_length=4000)
    references: list[VisualReference] = Field(default_factory=list, max_length=3)
    flow_tool: FlowTool = "standard"


class NarratedFlowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    request_id: UUID
    automatic_approval: bool = False
    # Requested clip length. The browser executor verifies it against Flow's
    # visible options and stops instead of rounding to another duration.
    clip_seconds: float = Field(default=6, ge=4, le=15, allow_inf_nan=False)


class NarratedSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class NarratedSelectVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    shot_index: int = Field(ge=0, le=89)
    # null removes the pin and returns to the newest completed retry.
    job_id: UUID | None
