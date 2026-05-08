"""ScheduledPost ORM model for content scheduling."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TEXT, TIMESTAMP, CheckConstraint, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ScheduledPost(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A post scheduled for future publishing on a social platform."""

    __tablename__ = "scheduled_posts"
    __table_args__ = (
        CheckConstraint(
            "content_type IN ('episode', 'audiobook')",
            name="sched_content_type_valid",
        ),
        CheckConstraint(
            "platform IN ('youtube', 'tiktok', 'instagram', 'x', 'facebook')",
            name="sched_platform_valid",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'publishing', 'published', 'failed', 'cancelled')",
            name="sched_status_valid",
        ),
        CheckConstraint(
            "privacy IN ('public', 'unlisted', 'private')",
            name="sched_privacy_valid",
        ),
        Index("ix_scheduled_posts_status", "status"),
        Index("ix_scheduled_posts_scheduled_at", "scheduled_at"),
        Index("ix_scheduled_posts_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_scheduled_posts_youtube_channel_id", "youtube_channel_id"),
    )

    content_type: Mapped[str] = mapped_column(TEXT, nullable=False)
    content_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    platform: Mapped[str] = mapped_column(TEXT, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(TEXT, nullable=False)
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    tags: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    privacy: Mapped[str] = mapped_column(TEXT, nullable=False, server_default="private")
    status: Mapped[str] = mapped_column(TEXT, nullable=False, server_default="scheduled")
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    remote_id: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    remote_url: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── YouTube channel for platform='youtube' ────────────────────────
    youtube_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("youtube_channels.id", ondelete="SET NULL"),
        nullable=True,
    )
