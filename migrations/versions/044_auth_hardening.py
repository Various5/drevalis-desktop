"""Auth hardening: login_events table + users.session_version column.

A.2 — ``login_events`` table: records every login attempt (success +
      failure) with user_id (nullable), IP, user-agent, timestamp, and
      failure_reason.  Indexed on (user_id, timestamp DESC) and
      (ip, timestamp DESC) for the typical Settings and admin lookups.

A.3 — ``users.session_version`` integer column (default 0): per-user
      token-revocation seam.  ``logout-everywhere`` increments it;
      ``_current_user`` rejects tokens whose ``sv`` claim doesn't match.

Revision ID: 044
Revises: 043
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "044"
down_revision: str | None = "043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    # ── login_events ───────────────────────────────────────────────────
    if not has_table("login_events"):
        op.create_table(
            "login_events",
            sa.Column(
                "id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("email_attempted", sa.Text(), nullable=True),
            sa.Column(
                "timestamp",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("ip", sa.Text(), nullable=False),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("failure_reason", sa.Text(), nullable=True),
        )

    if not has_index("login_events", "ix_login_events_user_ts"):
        op.create_index(
            "ix_login_events_user_ts",
            "login_events",
            ["user_id", "timestamp"],
        )

    if not has_index("login_events", "ix_login_events_ip_ts"):
        op.create_index(
            "ix_login_events_ip_ts",
            "login_events",
            ["ip", "timestamp"],
        )

    # ── users.session_version ──────────────────────────────────────────
    if not has_column("users", "session_version"):
        op.add_column(
            "users",
            sa.Column(
                "session_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if has_column("users", "session_version"):
        op.drop_column("users", "session_version")

    if has_index("login_events", "ix_login_events_ip_ts"):
        op.drop_index("ix_login_events_ip_ts", table_name="login_events")

    if has_index("login_events", "ix_login_events_user_ts"):
        op.drop_index("ix_login_events_user_ts", table_name="login_events")

    if has_table("login_events"):
        op.drop_table("login_events")
