"""Add ``ix_audiobooks_status`` index for Activity Monitor polling.

The Activity Monitor polls every 2-3 seconds asking which audiobooks
are in ``generating`` status. Without an index this is a sequential
scan of the audiobooks table on every poll — small now, but linear
in audiobook count and called continuously while the dashboard is open.

Revision ID: 037
Revises: 036
Create Date: 2026-04-29
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "037"
down_revision: str | None = "036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_index

    if not has_index("audiobooks", "ix_audiobooks_status"):
        op.create_index(
            "ix_audiobooks_status",
            "audiobooks",
            ["status"],
        )


def downgrade() -> None:
    op.drop_index("ix_audiobooks_status", table_name="audiobooks")
