"""
Base ORM model with UUID primary key and timestamp mixin.

All domain models inherit from Base, which provides a shared MetaData
with consistent constraint naming conventions.  The two mixins add:

- UUIDPrimaryKeyMixin  -- UUID PK via gen_random_uuid()
- TimestampMixin       -- created_at / updated_at TIMESTAMPTZ (UTC)

updated_at is auto-maintained by a PostgreSQL trigger created in the
initial Alembic migration (001).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, MetaData, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
    """Mixin: UUID primary key with server-side ``gen_random_uuid()`` AND
    Python-side ``uuid.uuid4`` defaults.

    The Python default is a belt-and-braces fallback for installs where
    the DB column was created without the server_default (early
    migrations that ran before the convention was applied). Without it,
    an INSERT that relies on the server default will 500 with
    ``NotNullViolationError`` on the ``id`` column.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """Mixin: created_at and updated_at TIMESTAMPTZ columns (UTC).

    Both default to now() on the server side.
    updated_at is additionally maintained by a PostgreSQL trigger.
    """

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
