"""Composite index on generation_jobs(episode_id, step).

The pipeline calls ``get_latest_by_episode_and_step`` once per step
(6 times per run) to resume skipping already-completed steps. Without
this index the query is an index-seek on ``ix_generation_jobs_episode_id``
followed by a sort on ``created_at`` — fine at one episode, but under
bulk generation the sort cost compounds. This composite index turns
each call into a single index range-scan.

Also adds an index on ``series.youtube_channel_id`` used by the
publish-scheduled-posts cron to resolve channel per series.

Revision ID: 018
Revises: 017
Create Date: 2026-04-21
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if not has_index("generation_jobs", "ix_generation_jobs_episode_id_step"):
        op.create_index(
            "ix_generation_jobs_episode_id_step",
            "generation_jobs",
            ["episode_id", "step"],
        )
    if not has_index("series", "ix_series_youtube_channel_id"):
        op.create_index(
            "ix_series_youtube_channel_id",
            "series",
            ["youtube_channel_id"],
        )


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    # drop_index guarded by caller per-table check
    op.drop_index("ix_series_youtube_channel_id", table_name="series")
    # drop_index guarded by caller per-table check
    op.drop_index("ix_generation_jobs_episode_id_step", table_name="generation_jobs")
