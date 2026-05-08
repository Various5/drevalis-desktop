"""Pydantic v2 request/response schemas for the Episode entity."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EpisodeCreate(BaseModel):
    """Payload for creating a new episode."""

    series_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    topic: str | None = None


class EpisodeUpdate(BaseModel):
    """Payload for updating an episode. All fields are optional."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    topic: str | None = None
    script: dict[str, Any] | None = None
    status: Literal["draft", "generating", "review", "editing", "exported", "failed"] | None = None
    override_voice_profile_id: UUID | None = None
    override_llm_config_id: UUID | None = None
    override_caption_style: str | None = None
    metadata_: dict[str, Any] | None = Field(default=None, alias="metadata_")


class ScriptUpdate(BaseModel):
    """Payload for updating just the script JSONB field."""

    script: dict[str, Any] = Field(..., description="EpisodeScript-compatible JSON object")


class MediaAssetResponse(BaseModel):
    """Nested media asset in episode detail."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_type: str
    file_path: str
    file_size_bytes: int | None
    duration_seconds: float | None
    scene_number: int | None
    generation_job_id: UUID | None
    created_at: datetime


class GenerationJobBrief(BaseModel):
    """Brief generation job info nested in episode detail."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    step: str
    status: str
    progress_pct: int
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    retry_count: int
    created_at: datetime


class EpisodeResponse(BaseModel):
    """Full episode detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    series_id: UUID
    title: str
    topic: str | None
    status: str
    script: dict[str, Any] | None
    base_path: str | None
    generation_log: dict[str, Any] | None
    metadata_: dict[str, Any] | None = Field(None, alias="metadata_")
    override_voice_profile_id: UUID | None
    override_llm_config_id: UUID | None
    override_caption_style: str | None
    content_format: str = "shorts"
    chapters: list[dict[str, Any]] | None = None
    total_duration_seconds: float | None = None
    created_at: datetime
    updated_at: datetime
    media_assets: list[MediaAssetResponse] = []
    generation_jobs: list[GenerationJobBrief] = []


class EpisodeListResponse(BaseModel):
    """Lightweight episode representation for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    series_id: UUID
    title: str
    topic: str | None
    status: str
    metadata_: dict[str, Any] | None = Field(None, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class GenerateRequest(BaseModel):
    """Optional overrides when kicking off generation."""

    voice_profile_id: UUID | None = None
    llm_config_id: UUID | None = None
    steps: (
        list[Literal["script", "voice", "scenes", "captions", "assembly", "thumbnail"]] | None
    ) = None


class GenerateResponse(BaseModel):
    """Response after enqueuing a generation job."""

    episode_id: UUID
    job_ids: list[UUID]
    message: str = "Generation enqueued"


class RetryResponse(BaseModel):
    """Response after enqueuing a retry."""

    episode_id: UUID
    job_id: UUID
    step: str
    message: str = "Retry enqueued"


# ── Video editing schemas ─────────────────────────────────────────────────


class BorderConfig(BaseModel):
    """Border / frame configuration for video editing."""

    width: int = Field(20, ge=0, le=200, description="Border width in pixels")
    color: str = Field("#000000", description="Border colour (hex or named)")
    style: Literal["solid", "rounded", "glow"] = "solid"


class VideoEditRequest(BaseModel):
    """Payload for applying edits to an episode video."""

    trim_start: float | None = Field(None, ge=0, description="Trim start in seconds")
    trim_end: float | None = Field(None, ge=0, description="Trim end in seconds")
    border: BorderConfig | None = None
    color_filter: Literal["warm", "cool", "bw", "vintage", "vivid", "dramatic", "sepia"] | None = (
        None
    )
    speed: float = Field(1.0, ge=0.25, le=4.0, description="Playback speed multiplier")


class VideoEditResponse(BaseModel):
    """Response after applying video edits."""

    episode_id: UUID
    message: str
    video_path: str | None = None
    duration_seconds: float | None = None


# ── Regeneration control schemas ──────────────────────────────────────────


class SetMusicRequest(BaseModel):
    """Payload for configuring background music settings on an episode.

    All fields are optional. Only fields explicitly provided are written
    into the episode's ``metadata_`` JSONB column, leaving other existing
    keys intact.
    """

    music_enabled: bool = Field(..., description="Whether to include background music")
    music_mood: str | None = Field(
        None,
        description=(
            "Mood keyword for background music selection "
            "(e.g. 'epic', 'calm', 'dramatic'). Pass null to clear."
        ),
    )
    music_volume_db: float | None = Field(
        None,
        ge=-40.0,
        le=0.0,
        description="Background music volume in dBFS. Typical range: -20 to -6.",
    )
    reassemble: bool = Field(
        True,
        description=(
            "If true (default), immediately enqueue a reassembly job "
            "(captions + assembly + thumbnail) so the change takes effect."
        ),
    )


class BulkGenerateRequest(BaseModel):
    """Payload for enqueuing generation for multiple episodes at once."""

    episode_ids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="UUIDs of episodes to generate. Only draft/failed episodes are queued.",
    )


class BulkGenerateResponse(BaseModel):
    """Summary of a bulk-generate request."""

    queued: int = Field(..., description="Number of episodes successfully enqueued")
    skipped: int = Field(
        ...,
        description=(
            "Number of episodes skipped (wrong status, already generating, "
            "or concurrency limit reached)"
        ),
    )
    total: int = Field(..., description="Total number of episode IDs submitted")
    queued_ids: list[UUID] = Field(..., description="IDs of the episodes that were enqueued")
    skipped_ids: list[UUID] = Field(..., description="IDs of the episodes that were skipped")
