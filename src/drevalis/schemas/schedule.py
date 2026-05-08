"""Pydantic schemas for content scheduling."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreate(BaseModel):
    content_type: Literal["episode", "audiobook"]
    content_id: UUID
    platform: Literal["youtube", "tiktok", "instagram", "x", "facebook"]
    scheduled_at: datetime
    title: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    tags: str = ""
    privacy: Literal["public", "unlisted", "private"] = "private"
    youtube_channel_id: UUID | None = None


class ScheduleUpdate(BaseModel):
    scheduled_at: datetime | None = None
    title: str | None = None
    description: str | None = None
    tags: str | None = None
    privacy: Literal["public", "unlisted", "private"] | None = None


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content_type: str
    content_id: UUID
    platform: str
    scheduled_at: datetime
    title: str
    description: str | None
    tags: str | None
    privacy: str
    status: str
    error_message: str | None
    published_at: datetime | None
    remote_id: str | None
    remote_url: str | None
    youtube_channel_id: UUID | None = None
    created_at: datetime


class CalendarDay(BaseModel):
    date: str  # ISO date "2026-03-28"
    posts: list[ScheduleResponse]


# ── Auto-schedule (Series-level batch scheduling) ─────────────────────────


class AutoScheduleRequest(BaseModel):
    """Request body for ``POST /api/v1/series/{id}/auto-schedule``."""

    cadence: Literal["daily", "every_n_days", "weekly"] = "daily"
    every_n: int = Field(
        default=1,
        ge=1,
        le=30,
        description="Step in days when ``cadence='every_n_days'``. Ignored otherwise.",
    )
    start_at: datetime = Field(
        ...,
        description=(
            "Earliest publish slot (in app timezone if naive). The scheduler "
            "rounds forward to the channel's first allowed weekday at the "
            "channel's configured upload_time."
        ),
    )
    episode_filter: Literal["review", "all_unuploaded"] = Field(
        default="all_unuploaded",
        description=(
            "Which episodes to schedule. ``review`` = only status='review'. "
            "``all_unuploaded`` = status in (review, exported) and no existing "
            "scheduled_post on YouTube."
        ),
    )
    privacy: Literal["public", "unlisted", "private"] = "private"
    description_template: str = Field(
        default="",
        description="Static description applied to every scheduled post.",
    )
    tags_template: str = Field(
        default="",
        description="Static comma-separated tags applied to every scheduled post.",
    )
    youtube_channel_id: UUID | None = Field(
        default=None,
        description=(
            "Override the series' default channel. Falls back to "
            "``series.youtube_channel_id`` when null."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description=(
            "When true, the planned slots are returned WITHOUT being persisted. "
            "Use to preview before committing."
        ),
    )


class PlannedSlot(BaseModel):
    """One slot in the auto-schedule plan."""

    episode_id: UUID
    episode_title: str
    scheduled_at: datetime
    privacy: str
    youtube_channel_id: UUID | None


class AutoScheduleResponse(BaseModel):
    """Result of an auto-schedule run."""

    series_id: UUID
    cadence: str
    planned: list[PlannedSlot]
    persisted: bool
    skipped_already_scheduled: list[UUID] = Field(
        default_factory=list,
        description=(
            "Episodes that were skipped because they already have a scheduled YouTube post."
        ),
    )


# ── Diagnostics (why are uploads failing?) ────────────────────────────────


class ChannelHealth(BaseModel):
    """Per-channel upload-readiness health."""

    channel_id: UUID
    channel_name: str | None
    has_access_token: bool
    has_refresh_token: bool
    token_expires_at: datetime | None
    token_expired: bool
    can_refresh: bool
    upload_days: list[str] | None
    upload_time: str | None
    issues: list[str] = Field(default_factory=list)


class UploadDiagnostic(BaseModel):
    """One scheduled post's diagnosis."""

    post_id: UUID
    status: str
    scheduled_at: datetime
    title: str
    platform: str
    error_message: str | None
    issues: list[str] = Field(default_factory=list)


class DiagnosticsResponse(BaseModel):
    """Aggregated upload health response."""

    channels: list[ChannelHealth]
    recent_failed_posts: list[UploadDiagnostic]
    overdue_scheduled_posts: list[UploadDiagnostic]
    summary: dict[str, int]


class RetryFailedRequest(BaseModel):
    """Body for the manual retry endpoint."""

    within_hours: int = Field(
        default=48,
        ge=1,
        le=720,
        description="Only retry posts whose scheduled_at is within the last N hours.",
    )
    post_ids: list[UUID] | None = Field(
        default=None,
        description=(
            "Specific post IDs to retry. When null, every failed post within "
            "the time window is reset."
        ),
    )


class RetryFailedResponse(BaseModel):
    requeued: list[UUID]
    skipped: list[UUID]
