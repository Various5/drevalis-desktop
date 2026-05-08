"""Asset ORM model — central media library.

Assets live outside any episode / audiobook. They're the raw building
blocks: uploaded reference images, B-roll videos, music, logos,
ingested raw clips. Anywhere the app needs a user-provided file beyond
the generated pipeline output, it references an ``asset_id``.

Deduplication is enforced by ``hash_sha256`` — uploading the same file
twice collapses into one row (the API returns the existing row).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import BIGINT, FLOAT, INT, JSON, TEXT, CheckConstraint, ForeignKey, Index
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Asset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user-provided media file stored in ``storage/assets/``.

    Kinds:
    - ``image``  : PNG / JPG. Used as reference for IPAdapter / as
                   direct scene source.
    - ``video``  : MP4 / MOV / WebM. Used as raw input to the
                   video-in pipeline, or as a scene's source clip.
    - ``audio``  : WAV / MP3 / FLAC. Used as custom music or sfx.
    - ``other``  : anything else the user wants to keep around.
    """

    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('image', 'video', 'audio', 'other')",
            name="ck_assets_kind_valid",
        ),
        Index("ix_assets_kind", "kind"),
        Index("ix_assets_created_at", "created_at"),
        Index("ix_assets_tags_gin", "tags", postgresql_using="gin"),
    )

    kind: Mapped[str] = mapped_column(TEXT, nullable=False)
    filename: Mapped[str] = mapped_column(TEXT, nullable=False)
    file_path: Mapped[str] = mapped_column(TEXT, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BIGINT, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    hash_sha256: Mapped[str] = mapped_column(TEXT, nullable=False, unique=True)
    width: Mapped[int | None] = mapped_column(INT, nullable=True)
    height: Mapped[int | None] = mapped_column(INT, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(FLOAT, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(TEXT), nullable=False, server_default="{}")
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class VideoIngestJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks an uploaded-video → candidate-clip-picker flow.

    Life cycle:
    1. ``queued`` — upload accepted, enqueued for processing
    2. ``running`` (stage=``transcribing``) — faster-whisper in progress
    3. ``running`` (stage=``analyzing``) — LLM picks candidate clips
    4. ``done`` — ``candidate_clips`` populated; UI shows the picker
    5. User picks one → ``selected_clip_index`` set,
       ``resulting_episode_id`` seeded with a draft episode whose scenes
       mirror the selected clip's segment.
    """

    __tablename__ = "video_ingest_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name="ck_video_ingest_status_valid",
        ),
        Index("ix_video_ingest_status", "status"),
    )

    asset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(TEXT, nullable=False, server_default="'queued'")
    progress_pct: Mapped[int] = mapped_column(INT, nullable=False, server_default="0")
    stage: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    transcript: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    candidate_clips: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    selected_clip_index: Mapped[int | None] = mapped_column(INT, nullable=True)
    resulting_episode_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
