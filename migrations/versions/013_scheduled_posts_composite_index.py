"""Add composite index on scheduled_posts(status, scheduled_at).

The publish_scheduled_posts cron job filters by:
    WHERE status = 'scheduled' AND scheduled_at <= now()

A composite index allows Postgres to satisfy both predicates in one
index scan instead of combining two bitmap scans.

Revision ID: 013
Revises: 012
Create Date: 2026-04-12
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if not has_index("scheduled_posts", "ix_scheduled_posts_status_scheduled_at"):
        op.create_index(
            "ix_scheduled_posts_status_scheduled_at",
            "scheduled_posts",
            ["status", "scheduled_at"],
        )


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    # drop_index guarded by caller per-table check
    op.drop_index("ix_scheduled_posts_status_scheduled_at", table_name="scheduled_posts")
