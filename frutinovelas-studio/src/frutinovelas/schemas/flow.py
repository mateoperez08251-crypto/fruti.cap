"""Provider-neutral requests: optional overrides never alter the saved scene."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FlowPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    project_id: UUID
    chapter_id: UUID
    scene_revisions: dict[UUID, int] = Field(min_length=1, max_length=100)
    generation_mode: Literal["image", "video", "image_video"] = "image"
    automatic_approval: bool = False
    # Natural-language Flow text, explicitly prepared by the user/client.
    # H3 syntax is not silently rewritten or sent as if Flow supported it.
    prompts: dict[UUID, str] = Field(default_factory=dict)
    video_prompts: dict[UUID, str] = Field(default_factory=dict)
    duration_seconds: float | None = Field(default=None, gt=0, le=60)
    # Registered image IDs per scene. When present they replace the cast references
    # for that scene's image; the saved scene is not modified.
    references: dict[UUID, list[UUID]] = Field(default_factory=dict)
    aspect_ratio: Literal["9:16", "16:9", "1:1", "4:3", "3:4"] | None = None
    flow_tool: Literal["standard", "storyboard_studio"] = "standard"


class FlowReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    decision: Literal["approved", "rejected"]


class FlowConnect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["assisted", "uia", "browser"] = "assisted"
    authorized: bool = False


class FlowRetry(BaseModel):
    request_id: UUID


class FlowResolve(BaseModel):
    confirmed_no_remote_work: bool = False
    note: str = Field(min_length=8, max_length=300)


class FlowImport(BaseModel):
    asset_id: UUID
