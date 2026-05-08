"""Episode ORM model."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, TEXT, CheckConstraint, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .generation_job import GenerationJob
    from .llm_config import LLMConfig
    from .media_asset import MediaAsset
    from .series import Series
    from .voice_profile import VoiceProfile


class Episode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single short-form video episode within a Series.

    status tracks the episode through the production pipeline:
      draft -> generating -> review -> editing -> exported
                          +-> failed

    The script JSONB column is validated through the EpisodeScript
    Pydantic schema before persistence.
    """

    __tablename__ = "episodes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'generating', 'review', 'editing', 'exported', 'failed')",
            name="status_valid",
        ),
        Index("ix_episodes_series_id_status", "series_id", "status"),
        Index("ix_episodes_status", "status"),
        Index("ix_episodes_created_at", "created_at"),
    )

    series_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(TEXT, nullable=False)
    topic: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    status: Mapped[str] = mapped_column(
        TEXT, nullable=False, default="draft", server_default="'draft'"
    )

    # Structured script data (validated via EpisodeScript Pydantic schema)
    script: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Relative path to the episode's media directory
    base_path: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # Human-readable reason the episode last failed. Written when the
    # pipeline aborts outside the per-step job scope (e.g. DB hiccup on
    # initial load, license flip mid-generation) so the UI has something
    # to show beyond "failed". Cleared on the next successful step start.
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # Opaque log of generation steps / events
    generation_log: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Publishing metadata (title, description, hashtags, thumbnail_path)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

    # ── Per-episode overrides (architect R4) ──────────────────────────
    override_voice_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voice_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    override_llm_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_configs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Per-episode caption style override (None = use series default)
    override_caption_style: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Long-form fields ─────────────────────────────────────────────
    content_format: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'shorts'"
    )
    chapters: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    total_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Asset-driven generation ──────────────────────────────────────
    # Per-episode reference assets override series-level ones when set.
    reference_asset_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Raw video clip this episode was produced from (video-in pipeline).
    # Nullable — episodes generated from topic prompts have no source.
    video_ingest_source_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Relationships ──────────────────────────────────────────────────
    series: Mapped[Series] = relationship(back_populates="episodes")
    override_voice_profile: Mapped[VoiceProfile | None] = relationship(
        back_populates="override_episodes",
        foreign_keys=[override_voice_profile_id],
    )
    override_llm_config: Mapped[LLMConfig | None] = relationship(
        back_populates="override_episodes",
        foreign_keys=[override_llm_config_id],
    )
    media_assets: Mapped[list[MediaAsset]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
    )
    generation_jobs: Mapped[list[GenerationJob]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
    )
