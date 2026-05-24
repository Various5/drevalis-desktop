"""add episodes.deleted_at for soft-delete

Revision ID: 7c1d9a2e4b30
Revises: 18bef6deb1fe
Create Date: 2026-05-24 00:00:00.000000

Soft-delete for episodes: a nullable ``deleted_at`` timestamp (NULL = live).
The repository excludes non-null rows from every read; delete sets it,
restore clears it. SQLite has no plain ADD COLUMN-with-index in one step, so
batch mode recreates the table reflecting its check constraint + indexes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import drevalis.models._types  # noqa: F401  custom TypeDecorators (JSONB / ARRAY / UUID)


# revision identifiers, used by Alembic.
revision: str = "7c1d9a2e4b30"
down_revision: Union[str, None] = "18bef6deb1fe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("episodes") as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_episodes_deleted_at", ["deleted_at"])


def downgrade() -> None:
    with op.batch_alter_table("episodes") as batch_op:
        batch_op.drop_index("ix_episodes_deleted_at")
        batch_op.drop_column("deleted_at")
