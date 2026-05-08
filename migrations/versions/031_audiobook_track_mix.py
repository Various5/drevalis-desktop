"""Add ``track_mix`` JSONB column to audiobooks for v0.24.0 mix controls.

Stores per-track gain offsets + mute flags (and v0.25.0 will hang
per-clip overrides under ``track_mix.clips``). Default is NULL,
which the audiobook service interprets as a passthrough mix —
existing audiobooks keep their current behaviour.

Revision ID: 031
Revises: 030
Create Date: 2026-04-26
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audiobooks",
        sa.Column(
            "track_mix",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("audiobooks", "track_mix")
