"""Validated audio-first storyboard payloads (no speech-to-text inference)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Motion = Literal["zoom_in", "zoom_out", "pan_left", "pan_right", "still"]
Aspect = Literal["9:16", "16:9"]


class NarratedShot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0, le=300, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, le=300, allow_inf_nan=False)
    text: str = Field(default="", max_length=2000)
    image_prompt: str = Field(default="", max_length=30000)
    image_asset_id: str | None = Field(default=None, max_length=36)
    motion: Motion = "zoom_in"

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_seconds <= self.start_seconds:
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
