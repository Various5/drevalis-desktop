"""align scheduled_posts privacy default to public

Revision ID: 18bef6deb1fe
Revises: 6bf6d3143c4c
Create Date: 2026-05-22 22:12:42.698542

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import drevalis.models._types  # custom TypeDecorators (JSONB / ARRAY / UUID)


# revision identifiers, used by Alembic.
revision: str = '18bef6deb1fe'
down_revision: Union[str, None] = '6bf6d3143c4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Align the column default with the application default flipped to
    # "public". Only affects future inserts that omit privacy; existing
    # rows are untouched. SQLite has no ALTER COLUMN DEFAULT, so batch mode
    # recreates the table (reflecting its check constraint + indexes).
    with op.batch_alter_table("scheduled_posts") as batch_op:
        batch_op.alter_column(
            "privacy",
            existing_type=sa.TEXT(),
            existing_nullable=False,
            server_default="public",
        )


def downgrade() -> None:
    with op.batch_alter_table("scheduled_posts") as batch_op:
        batch_op.alter_column(
            "privacy",
            existing_type=sa.TEXT(),
            existing_nullable=False,
            server_default="private",
        )
