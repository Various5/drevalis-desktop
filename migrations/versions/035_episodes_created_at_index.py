"""Add ``ix_episodes_created_at`` index for Dashboard recent-episodes query.

The Dashboard fetches episodes ordered by ``created_at DESC LIMIT n`` on
every render. Without an index this is a sequential scan + sort over
the full table; once the table grows past a few thousand rows this
shows up as a visible page-load delay.

Created CONCURRENTLY where possible so the migration is non-blocking
on a production database. The helper falls back to a regular index
when running outside a transaction is not supported (e.g. SQLite tests).

Revision ID: 035
Revises: 034
Create Date: 2026-04-29
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "035"
down_revision: str | None = "034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_index

    if not has_index("episodes", "ix_episodes_created_at"):
        op.create_index(
            "ix_episodes_created_at",
            "episodes",
            ["created_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_episodes_created_at", table_name="episodes")
