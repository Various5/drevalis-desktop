"""LLMConfig ORM model."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import INTEGER, NUMERIC, TEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .episode import Episode
    from .series import Series


class LLMConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Configuration for an OpenAI-compatible LLM endpoint.

    api_key_encrypted stores the Fernet-encrypted API key; api_key_version
    tracks the encryption key version to support key rotation.
    """

    __tablename__ = "llm_configs"

    name: Mapped[str] = mapped_column(TEXT, nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(TEXT, nullable=False)
    model_name: Mapped[str] = mapped_column(TEXT, nullable=False)

    # Fernet-encrypted API key + key-rotation version
    api_key_encrypted: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    api_key_version: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default="1")

    max_tokens: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default="4096")
    temperature: Mapped[Decimal] = mapped_column(NUMERIC, nullable=False, server_default="0.7")

    # ── Relationships ──────────────────────────────────────────────────
    series: Mapped[list[Series]] = relationship(
        back_populates="llm_config",
        foreign_keys="Series.llm_config_id",
    )
    override_episodes: Mapped[list[Episode]] = relationship(
        back_populates="override_llm_config",
        foreign_keys="Episode.override_llm_config_id",
    )
