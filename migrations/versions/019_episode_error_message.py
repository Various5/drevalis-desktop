"""Add episodes.error_message column.

Previously only ``generation_jobs`` carried an ``error_message``. If the
pipeline aborts before any job row is created (DB hiccup on initial
load, license flip mid-run, worker crash in startup code), the episode
flips to ``failed`` with no user-visible reason - the UI reads
``job.error_message`` and shows "Unknown error".

This column fills that gap. Written by the pipeline on any top-level
failure; cleared at the start of the next successful step.

Revision ID: 019
Revises: 018
Create Date: 2026-04-21
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if not has_column("episodes", "error_message"):
        op.add_column(
            "episodes",
            sa.Column("error_message", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if has_column("episodes", "error_message"):
        op.drop_column("episodes", "error_message")
