"""VideoTemplate ORM model.

Stores reusable video production presets that can be applied to any series.
A template captures the full aesthetic and audio configuration of a video so
users can reproduce a specific style (e.g. "Dark Sci-Fi Narrator") across
multiple series without manual reconfiguration.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import BOOLEAN, FLOAT, INTEGER, TEXT, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .voice_profile import VoiceProfile


class VideoTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reusable video production preset.

    Captures voice, visual, caption, music, and audio-mastering settings as a
    named profile.  Templates can be applied to a series in a single API call,
    copying every stored setting onto the series without overwriting fields
    that are absent from the template.

    The ``audio_settings`` JSONB column stores freeform audio-processing
    configuration (e.g. voice EQ bands, compressor ratios, reverb amount) that
    does not warrant individual columns because the exact shape may evolve over
    time without requiring migrations.

    Usage-tracking (``times_used``) is incremented atomically by the repository
    every time ``POST /{id}/apply/{series_id}`` is called, providing lightweight
    popularity signal for the UI.
    """

    __tablename__ = "video_templates"

    # ── Identity ──────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(TEXT, nullable=False)
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Voice settings ────────────────────────────────────────────────
    voice_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voice_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Visual settings ───────────────────────────────────────────────
    visual_style: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    # Allowed values: "image" | "video".  Not a DB-level constraint so that
    # new scene modes can be added at the application layer without migrations.
    scene_mode: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Caption settings ──────────────────────────────────────────────
    # Stores the preset name (e.g. "youtube_highlight", "karaoke") that maps
    # to a style definition in the CaptionService.
    caption_style_preset: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Music settings ────────────────────────────────────────────────
    music_enabled: Mapped[bool] = mapped_column(
        BOOLEAN, nullable=False, server_default=text("true")
    )
    music_mood: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    music_volume_db: Mapped[float] = mapped_column(
        FLOAT, nullable=False, server_default=text("'-14.0'")
    )

    # ── Audio mastering ───────────────────────────────────────────────
    # Freeform JSONB: voice_eq, compressor, reverb, loudness_target, etc.
    audio_settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )

    # ── Target duration ───────────────────────────────────────────────
    target_duration_seconds: Mapped[int] = mapped_column(
        INTEGER, nullable=False, server_default=text("30")
    )

    # ── Usage tracking ────────────────────────────────────────────────
    times_used: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default=text("0"))

    # ── Default flag ──────────────────────────────────────────────────
    # Only one template should carry is_default=True at a time.  Enforced
    # at the service/repository layer, not at the DB level, to avoid
    # complex partial-index management across dialects.
    is_default: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, server_default=text("false"))

    # ── Relationships ─────────────────────────────────────────────────
    voice_profile: Mapped[VoiceProfile | None] = relationship(
        foreign_keys=[voice_profile_id],
    )
