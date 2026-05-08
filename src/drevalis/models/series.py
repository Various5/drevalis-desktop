"""Series ORM model."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (  # noqa: F401
    BOOLEAN,
    INTEGER,
    JSON,
    NUMERIC,
    TEXT,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .comfyui import ComfyUIServer, ComfyUIWorkflow
    from .episode import Episode
    from .llm_config import LLMConfig
    from .prompt_template import PromptTemplate
    from .voice_profile import VoiceProfile
    from .youtube_channel import YouTubeChannel


class Series(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A content series that groups related episodes.

    Holds the default configuration (voice, LLM, ComfyUI workflow,
    prompt templates, visual style) that individual episodes inherit
    unless overridden at the episode level.
    """

    __tablename__ = "series"
    __table_args__ = (
        CheckConstraint(
            "target_duration_seconds IN (15, 30, 60)",
            name="target_duration_valid",
        ),
        Index("ix_series_youtube_channel_id", "youtube_channel_id"),
        Index("ix_series_content_format", "content_format"),
    )

    name: Mapped[str] = mapped_column(TEXT, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── FK references to configuration entities ────────────────────────
    voice_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voice_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    comfyui_server_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("comfyui_servers.id", ondelete="SET NULL"),
        nullable=True,
    )
    comfyui_workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("comfyui_workflows.id", ondelete="SET NULL"),
        nullable=True,
    )
    llm_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_configs.id", ondelete="SET NULL"),
        nullable=True,
    )
    script_prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    visual_prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Scalar columns ────────────────────────────────────────────────
    visual_style: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    character_description: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    target_duration_seconds: Mapped[int] = mapped_column(INTEGER, nullable=False)
    default_language: Mapped[str] = mapped_column(TEXT, nullable=False, server_default="en-US")

    # ── Quality upgrade columns ────────────────────────────────────────
    caption_style: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    negative_prompt: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Scene mode (image vs video) ───────────────────────────────────
    scene_mode: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'image'"))
    video_comfyui_workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("comfyui_workflows.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Background music ──────────────────────────────────────────────
    music_mood: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    music_volume_db: Mapped[float] = mapped_column(
        NUMERIC, nullable=False, server_default=text("'-14.0'")
    )
    music_enabled: Mapped[bool] = mapped_column(
        BOOLEAN, nullable=False, server_default=text("true")
    )

    # ── Long-form content settings ────────────────────────────────────
    content_format: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'shorts'")
    )
    target_duration_minutes: Mapped[int | None] = mapped_column(INTEGER, nullable=True)
    chapter_enabled: Mapped[bool] = mapped_column(
        BOOLEAN, nullable=False, server_default=text("true")
    )
    scenes_per_chapter: Mapped[int] = mapped_column(
        INTEGER, nullable=False, server_default=text("8")
    )
    transition_style: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transition_duration: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0.5")
    )
    duration_match_strategy: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'hold_frame'")
    )
    base_seed: Mapped[int | None] = mapped_column(INTEGER, nullable=True)
    intro_template: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    outro_template: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    visual_consistency_prompt: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    aspect_ratio: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'9:16'")
    )

    # ── Content quality settings ─────────────────────────────────────
    thumbnail_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'smart_frame'")
    )
    thumbnail_comfyui_workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("comfyui_workflows.id", ondelete="SET NULL"),
        nullable=True,
    )
    music_bpm: Mapped[int | None] = mapped_column(INTEGER, nullable=True)
    music_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    audio_preset: Mapped[str | None] = mapped_column(String(20), nullable=True)
    video_clip_duration: Mapped[int] = mapped_column(
        INTEGER, nullable=False, server_default=text("5")
    )

    # ── YouTube channel assignment ────────────────────────────────────
    youtube_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("youtube_channels.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Reference assets (IPAdapter / style conditioning) ────────────
    # List of asset UUIDs applied at the scenes step across every
    # episode in this series. Leave empty for pure prompt-driven gen.
    reference_asset_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # ── Phase E: character + style locks ─────────────────────────────
    # Opaque-to-us JSON that workflows consume as named inputs.
    # Shape: ``{"asset_ids": [...], "strength": 0.75, "lora": "..."}``
    # ``character_lock`` drives IPAdapter-FaceID; ``style_lock`` drives
    # style-reference flows. Workflows without the matching input slot
    # silently ignore these.
    character_lock: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    style_lock: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # ── Tone profile (script voice / banned vocab / style sample) ────
    # JSONB for fast partial reads in the script step. Validated by
    # ``schemas.series.ToneProfile`` at the API boundary; the column is
    # nullable so callers can clear it back to "no profile" by sending
    # ``null``. Existing rows after the 041 migration default to ``{}``.
    tone_profile: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        server_default=text("'{}'::jsonb"),
    )

    # ── Relationships ──────────────────────────────────────────────────
    voice_profile: Mapped[VoiceProfile | None] = relationship(
        back_populates="series",
        foreign_keys=[voice_profile_id],
    )
    comfyui_server: Mapped[ComfyUIServer | None] = relationship(
        back_populates="series",
        foreign_keys=[comfyui_server_id],
    )
    comfyui_workflow: Mapped[ComfyUIWorkflow | None] = relationship(
        back_populates="series",
        foreign_keys=[comfyui_workflow_id],
    )
    video_comfyui_workflow: Mapped[ComfyUIWorkflow | None] = relationship(
        foreign_keys=[video_comfyui_workflow_id],
    )
    llm_config: Mapped[LLMConfig | None] = relationship(
        back_populates="series",
        foreign_keys=[llm_config_id],
    )
    script_prompt_template: Mapped[PromptTemplate | None] = relationship(
        back_populates="series_as_script",
        foreign_keys=[script_prompt_template_id],
    )
    visual_prompt_template: Mapped[PromptTemplate | None] = relationship(
        back_populates="series_as_visual",
        foreign_keys=[visual_prompt_template_id],
    )
    youtube_channel: Mapped[YouTubeChannel | None] = relationship(
        foreign_keys=[youtube_channel_id],
    )
    episodes: Mapped[list[Episode]] = relationship(
        back_populates="series",
        cascade="all, delete-orphan",
    )
