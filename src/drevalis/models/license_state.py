"""License state singleton.

Only one row ever exists (``id=1``). Contains the signed JWT blob and
activation metadata. Stored as a row (not a file) because the app already
speaks Postgres and the JWT is self-authenticating — no extra encryption
layer needed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import TIMESTAMP, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from drevalis.models.base import Base


class LicenseStateRow(Base):
    __tablename__ = "license_state"

    # Fixed PK = 1 so there's always exactly one row (no composite logic needed).
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # Stored Fernet-encrypted when ``jwt_key_version`` is not None.
    # Legacy rows (jwt_key_version IS NULL) hold the raw JWT and are
    # transparently re-encrypted on the next write.
    jwt: Mapped[str | None] = mapped_column(Text, nullable=True)
    jwt_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Machine ID presented to the license server on last activate/heartbeat.
    # Persisted so we can show it in the UI and pass it on renewal.
    machine_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    activated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_heartbeat_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
