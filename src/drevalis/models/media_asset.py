"""MediaAsset ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BIGINT,
    INTEGER,
    NUMERIC,
    TEXT,
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .episode import Episode
    from .generation_job import GenerationJob


class MediaAsset(UUIDPrimaryKeyMixin, Base):
    """A file produced during episode generation.

    MediaAssets are immutable records — they have created_at but no
    updated_at (assets are never modified in place; a new asset is
    created instead).

    file_path is relative to STORAGE_BASE_PATH.
    """

    __tablename__ = "media_assets"
    __table_args__ = (
        CheckConstraint(
            "asset_type IN ("
            "'voiceover', 'scene', 'scene_image', 'scene_video', "
            "'caption', 'video', 'video_proxy', 'thumbnail', 'temp'"
            ")",
            name="asset_type_valid",
        ),
        Index("ix_media_assets_episode_id", "episode_id"),
        Index("ix_media_assets_episode_id_asset_type", "episode_id", "asset_type"),
        Index("ix_media_assets_episode_id_scene_number", "episode_id", "scene_number"),
    )

    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_type: Mapped[str] = mapped_column(TEXT, nullable=False)
    file_path: Mapped[str] = mapped_column(TEXT, nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    duration_seconds: Mapped[Decimal | None] = mapped_column(NUMERIC, nullable=True)
    scene_number: Mapped[int | None] = mapped_column(INTEGER, nullable=True)
    generation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generation_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    # ── Relationships ──────────────────────────────────────────────────
    episode: Mapped[Episode] = relationship(back_populates="media_assets")
    generation_job: Mapped[GenerationJob | None] = relationship(
        back_populates="media_assets",
        foreign_keys=[generation_job_id],
    )
