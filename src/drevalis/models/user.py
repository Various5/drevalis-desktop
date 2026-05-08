"""User ORM model — team / workspace membership."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BOOLEAN, INTEGER, TEXT, TIMESTAMP, CheckConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A human who logs into this Drevalis install.

    Role constraints:
    - ``owner``  : everything, including user management + billing.
    - ``editor`` : generate / publish / edit; cannot manage users or
                   change billing.
    - ``viewer`` : read-only; can inspect but not change anything.

    Self-hosted installs usually have exactly one owner and zero-to-a-
    few editors. The schema supports more but the UI is deliberately
    optimised for small teams.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')",
            name="role_valid",
        ),
        Index("ix_users_email", "email", unique=True),
    )

    email: Mapped[str] = mapped_column(TEXT, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(TEXT, nullable=False)
    role: Mapped[str] = mapped_column(TEXT, nullable=False, server_default="'owner'")
    display_name: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    is_active: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    # A.3 — per-user session version counter.  Incrementing this value
    # (via POST /auth/logout-everywhere) invalidates all existing HMAC-
    # signed session tokens for this user without touching Redis or a
    # server-side token store.  The ``sv`` claim is embedded in every new
    # token and validated on each request in ``_current_user``.
    session_version: Mapped[int] = mapped_column(
        INTEGER, nullable=False, server_default="0", default=0
    )

    # ── TOTP 2FA (migration 045) ───────────────────────────────────────
    # ``totp_confirmed_at IS NOT NULL`` is the gate for login enforcement.
    # The secret may exist before confirmation (pending enrolment); only
    # after the user verifies their first code does the login flow require
    # TOTP on subsequent logins.
    #
    # Recovery codes are stored encrypted (same Fernet key as the secret)
    # so they can be consumed and displayed back to the user.  They are
    # NOT hashed — hashing would prevent the "show which code was used"
    # UX on consumption.
    totp_secret_encrypted: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    totp_key_version: Mapped[int | None] = mapped_column(INTEGER, nullable=True)
    totp_confirmed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    totp_recovery_codes_encrypted: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Per-user UI preferences (migration 047) ────────────────────────
    # Free-form JSON object for client-side preferences that should
    # persist across browsers/devices. Top-level keys are namespaced by
    # feature (e.g. ``dashboard_layout``, ``theme``, ``calendar_view``).
    # The backend doesn't validate the shape — clients write what they
    # need and tolerate missing keys. Server default ``'{}'::jsonb`` so
    # legacy rows behave as "no preferences set".
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
