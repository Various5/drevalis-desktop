"""Pydantic v2 request/response schemas for YouTube integration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Channel schemas ──────────────────────────────────────────────────────


class YouTubeChannelResponse(BaseModel):
    """Public representation of a connected YouTube channel."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: str
    channel_name: str
    is_active: bool
    upload_days: list[str] | None = None
    upload_time: str | None = None
    created_at: datetime
    updated_at: datetime


class YouTubeChannelUpdate(BaseModel):
    """Payload for updating a YouTube channel's scheduling config."""

    upload_days: list[str] | None = None
    upload_time: str | None = None


class YouTubeAuthURLResponse(BaseModel):
    """Response containing the OAuth authorization URL."""

    auth_url: str


class YouTubeConnectionStatus(BaseModel):
    """Status of the YouTube connection."""

    connected: bool
    channel: YouTubeChannelResponse | None = None
    channels: list[YouTubeChannelResponse] = []


# ── Upload schemas ───────────────────────────────────────────────────────


class YouTubeUploadRequest(BaseModel):
    """Payload for initiating a YouTube upload."""

    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    privacy_status: Literal["public", "unlisted", "private"] = "private"
    channel_id: UUID | None = Field(
        default=None,
        description="Override channel. If omitted, uses the series' assigned channel.",
    )


class YouTubeUploadResponse(BaseModel):
    """Response after initiating or completing a YouTube upload."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    episode_id: UUID
    channel_id: UUID
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    title: str
    description: str | None = None
    privacy_status: str
    upload_status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class YouTubeUploadListResponse(BaseModel):
    """Lightweight upload record for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    episode_id: UUID
    channel_id: UUID
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    title: str
    privacy_status: str
    upload_status: str
    created_at: datetime


# ── Playlist schemas ─────────────────────────────────────────────────────


class PlaylistCreate(BaseModel):
    """Payload for creating a new YouTube playlist."""

    title: str = Field(..., min_length=1, max_length=150)
    description: str = Field(default="", max_length=5000)
    privacy_status: Literal["public", "unlisted", "private"] = "private"


class PlaylistResponse(BaseModel):
    """Full representation of a managed YouTube playlist."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    youtube_playlist_id: str
    title: str
    description: str | None = None
    privacy_status: str
    item_count: int
    created_at: datetime
    updated_at: datetime


class PlaylistAddVideo(BaseModel):
    """Payload for adding a video to a playlist."""

    video_id: str = Field(..., min_length=1)


# ── Analytics schemas ────────────────────────────────────────────────────


class VideoStatsResponse(BaseModel):
    """Statistics for a single YouTube video."""

    video_id: str
    title: str
    views: int
    likes: int
    comments: int
    published_at: str | None = None
