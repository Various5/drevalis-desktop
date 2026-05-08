"""VoiceProfile ORM model."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import NUMERIC, TEXT, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .episode import Episode
    from .series import Series


class VoiceProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reusable voice configuration (Piper, ElevenLabs, Kokoro, or Edge)."""

    __tablename__ = "voice_profiles"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('piper', 'elevenlabs', 'kokoro', 'edge', 'comfyui_elevenlabs')",
            name="provider_valid",
        ),
    )

    name: Mapped[str] = mapped_column(TEXT, nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(TEXT, nullable=False)

    # Piper-specific
    piper_model_path: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    piper_speaker_id: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # Shared tuning knobs
    speed: Mapped[Decimal] = mapped_column(NUMERIC, nullable=False, server_default="1.0")
    pitch: Mapped[Decimal] = mapped_column(NUMERIC, nullable=False, server_default="1.0")

    # ElevenLabs-specific
    elevenlabs_voice_id: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # Kokoro-specific
    kokoro_voice_name: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    kokoro_model_path: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # Edge TTS-specific
    edge_voice_id: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # Gender tag for voice casting
    gender: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # BCP-47 language tag ("en-US", "de-DE", "fr-FR"). Derived automatically
    # from edge_voice_id for Edge voices, user-set for Piper / Kokoro /
    # ElevenLabs where the locale isn't embedded in the ID. Nullable so
    # legacy voices aren't hidden from the picker until the operator
    # backfills them — UI treats NULL as "any language".
    language_code: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # Optional sample audio for preview
    sample_audio_path: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────
    series: Mapped[list[Series]] = relationship(
        back_populates="voice_profile",
        foreign_keys="Series.voice_profile_id",
    )
    override_episodes: Mapped[list[Episode]] = relationship(
        back_populates="override_voice_profile",
        foreign_keys="Episode.override_voice_profile_id",
    )
