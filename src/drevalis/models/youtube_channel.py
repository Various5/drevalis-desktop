"""YouTube channel and upload ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BOOLEAN, INTEGER, TEXT, TIMESTAMP, CheckConstraint, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .audiobook import Audiobook
    from .episode import Episode


class YouTubeChannel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A connected YouTube channel with encrypted OAuth tokens.

    Only one channel can be active at a time.  Tokens are Fernet-encrypted
    at rest using the application's ``ENCRYPTION_KEY``.
    """

    __tablename__ = "youtube_channels"
    __table_args__ = (Index("ix_youtube_channels_channel_id", "channel_id", unique=True),)

    channel_id: Mapped[str] = mapped_column(TEXT, nullable=False, unique=True)
    channel_name: Mapped[str] = mapped_column(TEXT, nullable=False)

    # Encrypted OAuth tokens (Fernet)
    access_token_encrypted: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    token_key_version: Mapped[int] = mapped_column(
        INTEGER, nullable=False, server_default=text("1")
    )

    token_expiry: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, server_default=text("true"))

    # ── Scheduling preferences ────────────────────────────────────────
    upload_days: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    upload_time: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────
    uploads: Mapped[list[YouTubeUpload]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
    )
    audiobook_uploads: Mapped[list[YouTubeAudiobookUpload]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
    )
    playlists: Mapped[list[YouTubePlaylist]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
    )


class YouTubeUpload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks a single YouTube upload attempt for an episode.

    upload_status: pending -> uploading -> done | failed
    """

    __tablename__ = "youtube_uploads"
    __table_args__ = (
        CheckConstraint(
            "upload_status IN ('pending', 'uploading', 'done', 'failed')",
            name="upload_status_valid",
        ),
        CheckConstraint(
            "privacy_status IN ('public', 'unlisted', 'private')",
            name="privacy_status_valid",
        ),
        Index("ix_youtube_uploads_episode_id", "episode_id"),
        Index("ix_youtube_uploads_channel_id", "channel_id"),
    )

    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("youtube_channels.id", ondelete="CASCADE"),
        nullable=False,
    )

    youtube_video_id: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    title: Mapped[str] = mapped_column(TEXT, nullable=False)
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    privacy_status: Mapped[str] = mapped_column(
        TEXT, nullable=False, server_default=text("'private'")
    )
    upload_status: Mapped[str] = mapped_column(
        TEXT, nullable=False, server_default=text("'pending'")
    )
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────
    episode: Mapped[Episode] = relationship()
    channel: Mapped[YouTubeChannel] = relationship(back_populates="uploads")


class YouTubeAudiobookUpload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks a single YouTube upload attempt for an audiobook.

    upload_status: pending -> uploading -> done | failed
    """

    __tablename__ = "youtube_audiobook_uploads"
    __table_args__ = (
        CheckConstraint(
            "upload_status IN ('pending', 'uploading', 'done', 'failed')",
            name="audiobook_upload_status_valid",
        ),
        CheckConstraint(
            "privacy_status IN ('public', 'unlisted', 'private')",
            name="audiobook_privacy_status_valid",
        ),
        Index("ix_youtube_audiobook_uploads_audiobook_id", "audiobook_id"),
        Index("ix_youtube_audiobook_uploads_channel_id", "channel_id"),
    )

    audiobook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audiobooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("youtube_channels.id", ondelete="CASCADE"),
        nullable=False,
    )

    youtube_video_id: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    title: Mapped[str] = mapped_column(TEXT, nullable=False)
    privacy_status: Mapped[str] = mapped_column(
        TEXT, nullable=False, server_default=text("'private'")
    )
    upload_status: Mapped[str] = mapped_column(
        TEXT, nullable=False, server_default=text("'pending'")
    )
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    playlist_id: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────
    audiobook: Mapped[Audiobook] = relationship()
    channel: Mapped[YouTubeChannel] = relationship(back_populates="audiobook_uploads")


class YouTubePlaylist(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A YouTube playlist managed by this application.

    Playlists are owned by a connected channel and can contain both
    episode uploads and audiobook uploads.
    """

    __tablename__ = "youtube_playlists"
    __table_args__ = (
        CheckConstraint(
            "privacy_status IN ('public', 'unlisted', 'private')",
            name="playlist_privacy_status_valid",
        ),
        Index("ix_youtube_playlists_channel_id", "channel_id"),
        Index("ix_youtube_playlists_youtube_playlist_id", "youtube_playlist_id"),
    )

    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("youtube_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    youtube_playlist_id: Mapped[str] = mapped_column(TEXT, nullable=False)
    title: Mapped[str] = mapped_column(TEXT, nullable=False)
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    privacy_status: Mapped[str] = mapped_column(
        TEXT, nullable=False, server_default=text("'private'")
    )
    item_count: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default=text("0"))

    # ── Relationships ──────────────────────────────────────────────────
    channel: Mapped[YouTubeChannel] = relationship(back_populates="playlists")
