"""ABTest ORM model — pairs two episodes for head-to-head performance comparison."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import TEXT, TIMESTAMP, CheckConstraint, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .episode import Episode
    from .series import Series


class ABTest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Pair of episodes belonging to the same series for A/B comparison.

    The ``variant_label`` string is creator-authored ("different hook
    opening", "male vs female voice", etc.) and exists purely so the UI
    can show the operator what each test was actually measuring.

    A scheduled worker (future) wakes up 7 days after the later of the
    two episodes' YouTube upload completes, fetches both episodes'
    Analytics, and fills in ``winner_episode_id`` + ``comparison_at``.
    """

    __tablename__ = "ab_tests"
    __table_args__ = (
        CheckConstraint(
            "episode_a_id <> episode_b_id",
            name="distinct_episodes",
        ),
        Index("ix_ab_tests_series_id_q", "series_id"),
    )

    series_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=False,
    )
    episode_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    episode_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_label: Mapped[str] = mapped_column(TEXT, nullable=False)
    notes: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    winner_episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    comparison_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    series: Mapped[Series] = relationship(foreign_keys=[series_id])
    episode_a: Mapped[Episode] = relationship(foreign_keys=[episode_a_id])
    episode_b: Mapped[Episode] = relationship(foreign_keys=[episode_b_id])
