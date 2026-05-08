"""GenerationJob ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import INTEGER, TEXT, TIMESTAMP, CheckConstraint, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .episode import Episode
    from .media_asset import MediaAsset


class GenerationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks a single pipeline step execution for an episode.

    Each episode generation spawns one GenerationJob per pipeline step
    (script, voice, scenes, captions, assembly, thumbnail).
    """

    __tablename__ = "generation_jobs"
    __table_args__ = (
        CheckConstraint(
            "step IN ('script', 'voice', 'scenes', 'captions', 'assembly', 'thumbnail')",
            name="step_valid",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name="status_valid",
        ),
        Index("ix_generation_jobs_episode_id", "episode_id"),
        Index("ix_generation_jobs_status", "status"),
        Index("ix_generation_jobs_episode_id_step", "episode_id", "step"),
    )

    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    step: Mapped[str] = mapped_column(TEXT, nullable=False)
    status: Mapped[str] = mapped_column(TEXT, nullable=False, server_default="'queued'")
    progress_pct: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    retry_count: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default="0")
    worker_id: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Long-form granular tracking ──────────────────────────────────
    chapter_number: Mapped[int | None] = mapped_column(INTEGER, nullable=True)
    scene_number: Mapped[int | None] = mapped_column(INTEGER, nullable=True)
    total_items: Mapped[int | None] = mapped_column(INTEGER, nullable=True)
    completed_items: Mapped[int | None] = mapped_column(INTEGER, nullable=True)

    # ── LLM token accounting ─────────────────────────────────────────
    # Accumulated input/output tokens across every LLM call this step
    # made. Zero for steps that don't touch an LLM (voice, scenes,
    # captions, assembly, thumbnail). Populated via the
    # drevalis.core.usage context-var tracker — see that module for
    # the contract.
    tokens_prompt: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default="0")
    tokens_completion: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default="0")

    # ── Relationships ──────────────────────────────────────────────────
    episode: Mapped[Episode] = relationship(back_populates="generation_jobs")
    media_assets: Mapped[list[MediaAsset]] = relationship(
        back_populates="generation_job",
        foreign_keys="MediaAsset.generation_job_id",
    )
