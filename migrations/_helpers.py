"""Idempotency helpers for Alembic migrations.

Every migration that creates a table, adds a column, or installs an
index should wrap the DDL in one of these helpers — that way a
partial run, a DB-copied-from-prod, or a manual schema tweak doesn't
hard-fail ``alembic upgrade head`` on re-run.

Usage::

    from migrations._helpers import has_column, has_table, has_index

    def upgrade() -> None:
        if not has_table("episodes"):
            op.create_table("episodes", ...)
        if not has_column("episodes", "thumbnail_mode"):
            op.add_column("episodes", sa.Column("thumbnail_mode", sa.Text(), nullable=True))
        if not has_index("episodes", "ix_episodes_status"):
            op.create_index("ix_episodes_status", "episodes", ["status"])

The helpers bind to ``op.get_bind()``; callers must be inside an
Alembic migration context.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def _inspector():  # type: ignore[no-untyped-def]
    return sa.inspect(op.get_bind())


def has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def has_column(table: str, column: str) -> bool:
    if not has_table(table):
        return False
    return column in {c["name"] for c in _inspector().get_columns(table)}


def has_index(table: str, index: str) -> bool:
    if not has_table(table):
        return False
    return index in {i["name"] for i in _inspector().get_indexes(table)}


def has_constraint(table: str, constraint: str) -> bool:
    """True if any check / unique / foreign-key / primary-key
    constraint on *table* has the given name. Useful for the
    double-prefixed ``ck_*`` legacy names introduced by migration 016
    — see ``030_facebook_platform`` for the runtime introspection
    pattern that covers doubly-prefixed names."""
    if not has_table(table):
        return False
    insp = _inspector()
    names: set[str] = set()
    for check in insp.get_check_constraints(table):
        if check.get("name"):
            names.add(check["name"])
    for uniq in insp.get_unique_constraints(table):
        if uniq.get("name"):
            names.add(uniq["name"])
    for fk in insp.get_foreign_keys(table):
        if fk.get("name"):
            names.add(fk["name"])
    pk = insp.get_pk_constraint(table)
    if pk and pk.get("name"):
        names.add(pk["name"])
    return constraint in names


__all__ = ["has_table", "has_column", "has_index", "has_constraint"]
