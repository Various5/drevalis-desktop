"""Social platform and upload ORM models for multi-platform distribution."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BIGINT,
    BOOLEAN,
    INTEGER,
    JSON,
    TEXT,
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .episode import Episode


class SocialPlatform(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A connected social media platform account with encrypted credentials.

    Supported platforms: tiktok, instagram, x (Twitter/X), facebook.
    Only one account per platform can be active at a time.
    Tokens are Fernet-encrypted at rest using the application's ENCRYPTION_KEY.
    """

    __tablename__ = "social_platforms"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('tiktok', 'instagram', 'x', 'facebook')",
            name="platform_valid",
        ),
        Index("ix_social_platforms_platform", "platform"),
        Index("ix_social_platforms_platform_account", "platform", "account_id", unique=True),
    )

    platform: Mapped[str] = mapped_column(TEXT, nullable=False)
    account_name: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    account_id: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # Encrypted OAuth / API tokens (Fernet)
    access_token_encrypted: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    token_key_version: Mapped[int] = mapped_column(
        INTEGER, nullable=False, server_default=text("1")
    )

    token_expires_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, server_default=text("true"))

    # Platform-specific config (public_video_base_url for IG, etc).
    account_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────
    uploads: Mapped[list[SocialUpload]] = relationship(
        back_populates="platform_account",
        cascade="all, delete-orphan",
    )


class SocialUpload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks a single upload attempt to a social platform.

    upload_status: pending -> uploading -> done | failed
    content_type: episode | audiobook
    """

    __tablename__ = "social_uploads"
    __table_args__ = (
        CheckConstraint(
            "upload_status IN ('pending', 'uploading', 'done', 'failed')",
            name="social_upload_status_valid",
        ),
        CheckConstraint(
            "content_type IN ('episode', 'audiobook')",
            name="social_content_type_valid",
        ),
        Index("ix_social_uploads_platform_id", "platform_id"),
        Index("ix_social_uploads_episode_id", "episode_id"),
        Index("ix_social_uploads_content_type", "content_type"),
    )

    platform_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_platforms.id", ondelete="CASCADE"),
        nullable=False,
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=True,
    )

    content_type: Mapped[str] = mapped_column(
        TEXT, nullable=False, server_default=text("'episode'")
    )

    # Platform-specific identifiers
    platform_content_id: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    platform_url: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    title: Mapped[str] = mapped_column(TEXT, nullable=False)
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    hashtags: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    upload_status: Mapped[str] = mapped_column(
        TEXT, nullable=False, server_default=text("'pending'")
    )
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # Engagement counters (updated via periodic sync)
    views: Mapped[int] = mapped_column(BIGINT, nullable=False, server_default=text("0"))
    likes: Mapped[int] = mapped_column(BIGINT, nullable=False, server_default=text("0"))
    comments: Mapped[int] = mapped_column(BIGINT, nullable=False, server_default=text("0"))
    shares: Mapped[int] = mapped_column(BIGINT, nullable=False, server_default=text("0"))

    # ── Relationships ──────────────────────────────────────────────────
    platform_account: Mapped[SocialPlatform] = relationship(back_populates="uploads")
    episode: Mapped[Episode | None] = relationship()
