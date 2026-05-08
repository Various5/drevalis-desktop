"""PasswordResetToken ORM model.

One row per password-reset request.  The raw token is never persisted;
only its SHA-256 hex digest is stored so a database dump cannot be used
to hijack an active reset link (CWE-916).

Token lifecycle:
  1. ``request_reset`` mints a raw token, stores the hash + an
     ``expires_at`` 60 minutes in the future, and emails the raw token
     to the user.
  2. ``consume_reset`` hashes the incoming raw token, finds an unused
     unexpired row, marks ``used_at = now()``, and updates the user's
     password + session_version.

Sibling tokens (same user_id, used_at IS NULL, not expired) are
invalidated on a successful reset so only one reset is ever "live" for
a given account.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TEXT, TIMESTAMP, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PasswordResetToken(Base):
    """One password-reset token row."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        # Fast lookup: find unused unexpired tokens for a given user.
        Index("ix_prt_user_used_expires", "user_id", "used_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    # CASCADE: deleting a user removes their pending reset tokens too.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # SHA-256 hex digest of the raw URL-safe token.
    token_hash: Mapped[str] = mapped_column(TEXT, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    # Absolute expiry — service layer sets this to now() + 60 minutes.
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    # NULL = unconsumed; written to now() the first (and only) time the
    # token is redeemed.
    used_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
