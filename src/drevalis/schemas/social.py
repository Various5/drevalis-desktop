"""Pydantic v2 request/response schemas for social platform integration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Platform schemas ────────────────────────────────────────────────────


class PlatformConnect(BaseModel):
    """Payload for connecting a new social platform account.

    * ``account_id`` is the platform-specific identifier uploads need.
      Facebook expects the Page ID here; Instagram expects the
      Business/Creator account ID; TikTok/X populate it from OAuth.
    * ``account_metadata`` carries platform-specific knobs — e.g.
      Instagram uses ``{"public_video_base_url": "https://..."}`` because
      Reels require an HTTPS URL to reach the file.
    """

    platform: Literal["tiktok", "instagram", "x", "facebook"]
    account_name: str = Field(..., min_length=1, max_length=255)
    account_id: str | None = Field(default=None, max_length=255)
    access_token: str = Field(..., min_length=1)
    refresh_token: str | None = None
    account_metadata: dict[str, str] | None = None


class PlatformResponse(BaseModel):
    """Public representation of a connected social platform account."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: str
    account_id: str | None = None
    account_name: str | None = None
    is_active: bool
    has_access_token: bool = False
    has_refresh_token: bool = False
    created_at: datetime
    updated_at: datetime


# ── Upload schemas ──────────────────────────────────────────────────────


class SocialUploadRequest(BaseModel):
    """Payload for initiating a social media upload."""

    platform_id: UUID
    episode_id: UUID | None = None
    content_type: Literal["episode", "audiobook"] = "episode"
    title: str = Field(..., min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    hashtags: str = Field(default="", max_length=1000)


class SocialUploadResponse(BaseModel):
    """Response after initiating or completing a social upload."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform_id: UUID
    episode_id: UUID | None = None
    content_type: str
    platform_content_id: str | None = None
    platform_url: str | None = None
    title: str
    description: str | None = None
    hashtags: str | None = None
    upload_status: str
    error_message: str | None = None
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    created_at: datetime
    updated_at: datetime


# ── TikTok OAuth schemas ─────────────────────────────────────────────────


class TikTokAuthURLResponse(BaseModel):
    """Response for the TikTok auth-URL endpoint."""

    auth_url: str = Field(..., description="Full TikTok OAuth 2.0 authorization URL.")
    state: str = Field(
        ...,
        description="CSRF state token. The frontend should store and verify this.",
    )


class TikTokConnectionStatus(BaseModel):
    """Current TikTok connection state for the settings UI."""

    connected: bool
    account: PlatformResponse | None = None


# ── Stats schemas ───────────────────────────────────────────────────────


class PlatformStats(BaseModel):
    """Aggregated statistics for a single platform."""

    platform: str
    total_uploads: int
    successful_uploads: int
    total_views: int
    total_likes: int
    total_comments: int
    total_shares: int


class OverallStats(BaseModel):
    """Overall statistics across all platforms."""

    platforms: list[PlatformStats]
    total_platforms_connected: int
    total_uploads: int
    total_views: int
    total_likes: int
