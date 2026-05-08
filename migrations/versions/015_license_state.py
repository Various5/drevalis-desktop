"""Add license_state singleton table.

Stores the signed license JWT plus activation metadata. Exactly one row
(id = 1) is used; the upsert path in the repository enforces this.

Revision ID: 015
Revises: 014
Create Date: 2026-04-19
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if not has_table("license_state"):
        op.create_table(
            "license_state",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("jwt", sa.Text(), nullable=True),
            sa.Column("machine_id", sa.String(length=32), nullable=True),
            sa.Column("activated_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("last_heartbeat_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("last_heartbeat_status", sa.String(length=32), nullable=True),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint("id = 1", name="ck_license_state_singleton"),
        )


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if has_table("license_state"):
        op.drop_table("license_state")
