"""Character pack — reusable bundle of character_lock + style_lock."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, TEXT
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CharacterPack(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A saved bundle of character_lock + style_lock plus a display name.

    Applied to a Series by copying the lock payloads onto the series row —
    after that the pack is independent, so deleting a pack doesn't
    retroactively change any series using it.
    """

    __tablename__ = "character_packs"

    name: Mapped[str] = mapped_column(TEXT, nullable=False)
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    thumbnail_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    character_lock: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    style_lock: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
