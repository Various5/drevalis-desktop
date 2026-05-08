"""Video edit session — persistent state for the in-browser editor."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import TIMESTAMP, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class VideoEditSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One edit session per episode — the in-browser editor's save file."""

    __tablename__ = "video_edit_sessions"

    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    timeline: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    last_render_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_rendered_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
