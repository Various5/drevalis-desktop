"""Add users table for team / workspace mode.

Self-hosted Drevalis ships as single-user by default (the 99% case).
Team mode opt-in: invite additional users who share the same install
with role-scoped permissions. ``owner`` can do everything including
managing users; ``editor`` can generate / publish but not manage the
team or billing; ``viewer`` is read-only.

An environment-variable seed path (``OWNER_EMAIL`` / ``OWNER_PASSWORD``
on first-run) lets operators bootstrap without going through an HTTP
flow. After that, further users are invited through the UI.

Revision ID: 024
Revises: 023
Create Date: 2026-04-22
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "024"
down_revision: str | None = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent: skip if the table already exists. Useful when a dev
    # DB was hand-created ahead of the migration landing, or a partial
    # run left the table behind before a later migration failed.
    from migrations._helpers import has_index, has_table

    if not has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("email", sa.Text(), nullable=False, unique=True),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("role", sa.Text(), nullable=False, server_default="'owner'"),
            sa.Column("display_name", sa.Text(), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.CheckConstraint(
                "role IN ('owner', 'editor', 'viewer')",
                name="ck_users_role_valid",
            ),
        )
    if not has_index("users", "ix_users_email_q"):
        op.create_index("ix_users_email_q", "users", ["email"])


def downgrade() -> None:
    from migrations._helpers import has_index, has_table

    if has_index("users", "ix_users_email_q"):
        op.drop_index("ix_users_email_q", table_name="users")
    if has_table("users"):
        op.drop_table("users")
