"""Pydantic v2 request/response schemas for the VideoTemplate entity."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VideoTemplateCreate(BaseModel):
    """Payload for creating a new video template.

    Only ``name`` is required.  All other fields are optional so that a
    template can be built incrementally, capturing only the settings the
    user wants to standardise.
    """

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None

    # Voice
    voice_profile_id: UUID | None = None

    # Visual
    visual_style: str | None = None
    scene_mode: str | None = None  # "image" | "video"

    # Caption
    caption_style_preset: str | None = None

    # Music
    music_enabled: bool = True
    music_mood: str | None = None
    music_volume_db: float = -14.0

    # Audio mastering (freeform JSONB)
    audio_settings: dict[str, Any] | None = None

    # Target duration
    target_duration_seconds: int = Field(default=30, ge=1, le=3600)

    # Default flag
    is_default: bool = False


class VideoTemplateUpdate(BaseModel):
    """Payload for updating a video template.  Every field is optional."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    voice_profile_id: UUID | None = None
    visual_style: str | None = None
    scene_mode: str | None = None
    caption_style_preset: str | None = None
    music_enabled: bool | None = None
    music_mood: str | None = None
    music_volume_db: float | None = None
    audio_settings: dict[str, Any] | None = None
    target_duration_seconds: int | None = Field(default=None, ge=1, le=3600)
    is_default: bool | None = None


class VideoTemplateResponse(BaseModel):
    """Full video template response, serialisable directly from the ORM model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    voice_profile_id: UUID | None
    visual_style: str | None
    scene_mode: str | None
    caption_style_preset: str | None
    music_enabled: bool
    music_mood: str | None
    music_volume_db: float
    audio_settings: dict[str, Any] | None
    target_duration_seconds: int
    times_used: int
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ApplyTemplateResponse(BaseModel):
    """Response after applying a template to a series.

    Reports which fields were actually written to the series so callers
    can distinguish a full apply from a partial one (where some template
    fields were ``None`` and therefore skipped).
    """

    series_id: UUID
    template_id: UUID
    applied_fields: list[str]
    message: str


class CreateFromSeriesResponse(BaseModel):
    """Response after creating a template from an existing series."""

    template: VideoTemplateResponse
    message: str
