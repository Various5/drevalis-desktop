"""PromptTemplate ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import TEXT, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .series import Series


class PromptTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reusable LLM prompt template with placeholders.

    template_type determines where the template is used in the pipeline:
    - script   : full episode script generation
    - visual   : per-scene image-prompt refinement
    - hook     : hook/opening-line generation
    - hashtag  : hashtag / description generation

    user_prompt_template supports {topic}, {character}, {duration} placeholders
    that are filled at generation time.
    """

    __tablename__ = "prompt_templates"
    __table_args__ = (
        CheckConstraint(
            "template_type IN ('script', 'visual', 'hook', 'hashtag')",
            name="template_type_valid",
        ),
    )

    name: Mapped[str] = mapped_column(TEXT, nullable=False, unique=True)
    template_type: Mapped[str] = mapped_column(TEXT, nullable=False)
    system_prompt: Mapped[str] = mapped_column(TEXT, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(TEXT, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────
    series_as_script: Mapped[list[Series]] = relationship(
        back_populates="script_prompt_template",
        foreign_keys="Series.script_prompt_template_id",
    )
    series_as_visual: Mapped[list[Series]] = relationship(
        back_populates="visual_prompt_template",
        foreign_keys="Series.visual_prompt_template_id",
    )
