"""Add ``settings_json`` JSONB column to audiobooks (Task 9).

Stores the resolved AudiobookSettings (preset + settings_override merged)
so the worker job doesn't have to re-resolve at job run time. NULL means
"narrative defaults" — pre-Task-9 audiobooks keep their current behaviour
because every settings consumer falls back to the narrative profile when
``settings_json`` is unset.

Revision ID: 032
Revises: 031
Create Date: 2026-04-27
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "032"
down_revision: str | None = "031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audiobooks",
        sa.Column(
            "settings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("audiobooks", "settings_json")
