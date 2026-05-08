"""Cross-dialect column types for the desktop port.

Centralises the JSON/UUID/ARRAY decisions so models stay portable between
PostgreSQL (the historical backend, still in scope as a future SaaS option
per SCOPE.md) and SQLite (single-user desktop default).

Re-exported names match the original ``sqlalchemy.dialects.postgresql``
symbols so models switch with a one-line import change. The Postgres
behavior is preserved on Postgres; SQLite gets a portable equivalent.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON
from sqlalchemy import Uuid as _Uuid
from sqlalchemy.dialects.postgresql import ARRAY as _PG_ARRAY
from sqlalchemy.dialects.postgresql import JSONB as _PG_JSONB
from sqlalchemy.types import TypeDecorator

__all__ = ["ARRAY", "JSONB", "UUID"]


class JSONB(TypeDecorator):  # type: ignore[type-arg]
    """JSONB on PostgreSQL, JSON on SQLite.

    Both round-trip dicts/lists transparently. Postgres keeps the binary-
    JSON representation and indexing operators; SQLite uses its JSON1
    extension which provides functionally equivalent ``json_extract``
    queries without the on-disk binary format.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PG_JSONB())
        return dialect.type_descriptor(JSON())


class ARRAY(TypeDecorator):  # type: ignore[type-arg]
    """Postgres ARRAY on PG, JSON-encoded list on SQLite.

    Constructed exactly like ``postgresql.ARRAY(item_type)``. On SQLite
    the list is stored as a JSON array — querying loses the ANY/ALL
    operators but retains list-membership via ``json_each``.

    Use Python-side ``default=list`` rather than ``server_default``,
    because the empty-array literal differs (``'{}'`` on PG vs ``'[]'``
    on SQLite).
    """

    impl = JSON
    cache_ok = True

    def __init__(self, item_type: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._item_type = item_type

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PG_ARRAY(self._item_type))
        return dialect.type_descriptor(JSON())


# SQLAlchemy 2.0+ ships a dialect-aware ``Uuid`` (native ``UUID`` on
# Postgres, ``CHAR(32)`` on others). Re-export under the historical
# ``UUID`` name so call sites like ``UUID(as_uuid=True)`` keep working.
UUID = _Uuid
