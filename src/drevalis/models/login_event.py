"""LoginEvent ORM model — audit log for every login attempt.

Records both successes and failures so operators can inspect suspicious
activity per-user or per-IP without touching application logs.

Columns kept deliberately narrow:
- user_id: nullable — unknown-email failures have no resolvable user.
- email_attempted: populated on failures for unknown emails; NULL on success
  (user_id carries the identity there, and storing the email twice on every
  success row is redundant).
- failure_reason: one of the controlled values the login path writes;
  ``totp_required`` is reserved for Package B (TOTP 2FA) and present now so
  the column doesn't need a second migration later.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BOOLEAN, TEXT, TIMESTAMP, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LoginEvent(Base):
    """One row per login attempt (success or failure)."""

    __tablename__ = "login_events"
    __table_args__ = (
        # Fast per-user timeline queries (Settings > Recent logins).
        Index("ix_login_events_user_ts", "user_id", "timestamp"),
        # Fast per-IP queries (admin security audit / rate-limit archaeology).
        Index("ix_login_events_ip_ts", "ip", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    # Nullable: unknown-email failures have no user_id.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Populated on unknown-email failures; NULL on success / wrong-password
    # (user_id already identifies the account in those cases).
    email_attempted: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    ip: Mapped[str] = mapped_column(TEXT, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    success: Mapped[bool] = mapped_column(BOOLEAN, nullable=False)

    # "unknown_email" | "wrong_password" | "inactive_user" |
    # "rate_limited" | "totp_required" | NULL (success)
    failure_reason: Mapped[str | None] = mapped_column(TEXT, nullable=True)
