"""Index ``series.content_format`` for the priority-deferral JOIN.

The worker's job-dispatch path (workers/jobs/episode.py) issues raw-SQL
JOINs from episodes onto series with
``WHERE s.content_format = :fmt`` to decide whether to defer a job
behind the configured priority order (shorts_first / longform_first).
On every check that's a sequential scan of the series table; once a
user has dozens of series this dominates the dispatch loop.

Revision ID: 039
Revises: 038
Create Date: 2026-04-29
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "039"
down_revision: str | None = "038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_index

    if not has_index("series", "ix_series_content_format"):
        op.create_index(
            "ix_series_content_format",
            "series",
            ["content_format"],
        )


def downgrade() -> None:
    op.drop_index("ix_series_content_format", table_name="series")
