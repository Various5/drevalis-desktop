"""
Base ORM model with UUID primary key and timestamp mixin.

All domain models inherit from Base, which provides shared MetaData with
consistent constraint naming. The two mixins add:

- UUIDPrimaryKeyMixin  -- Python-side ``uuid.uuid4`` default (no DB-side
                          ``gen_random_uuid()`` — that's Postgres-only).
- TimestampMixin       -- created_at / updated_at TIMESTAMPTZ (UTC),
                          maintained at the SQLAlchemy layer (server-side
                          triggers were Postgres-specific; SQLite has no
                          equivalent and the desktop port doesn't need
                          one given the worker is the only writer).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from drevalis.models._types import UUID

# ── Naming convention for constraints (Alembic autogenerate-friendly) ──────
convention = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with shared naming-convention metadata."""

    metadata = MetaData(naming_convention=convention)


class UUIDPrimaryKeyMixin:
    """Mixin: UUID primary key with Python-side ``uuid.uuid4`` default."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Mixin: created_at / updated_at TIMESTAMPTZ columns (UTC).

    Both default to ``CURRENT_TIMESTAMP`` server-side; ``updated_at``
    is additionally bumped by SQLAlchemy on update. Cross-dialect:
    ``func.current_timestamp()`` compiles to ``CURRENT_TIMESTAMP`` on
    SQLite and ``now()`` on Postgres.
    """

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
