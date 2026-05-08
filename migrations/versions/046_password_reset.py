"""Password-reset tokens table.

Adds ``password_reset_tokens`` to support the forgot-password flow:

* ``id``          — UUID primary key.
* ``user_id``     — FK → users.id, CASCADE on delete so orphaned tokens
                    are cleaned up automatically when a user is removed.
* ``token_hash``  — SHA-256 hex digest of the raw token.  Storing the
                    hash prevents a DB dump from leaking live tokens.
* ``created_at``  — server-side now().
* ``expires_at``  — set 60 minutes after creation by the service layer.
* ``used_at``     — NULL while the token is unconsumed; written to now()
                    on first successful use.

Index on ``(user_id, used_at, expires_at)`` supports the "find unused
unexpired tokens for this user" query issued by both request_reset
(cap enforcement) and consume_reset (lookup).

Revision ID: 046
Revises: 045
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "046"
down_revision: str | None = "045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_index, has_table

    if not has_table("password_reset_tokens"):
        op.create_table(
            "password_reset_tokens",
            sa.Column(
                "id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # SHA-256 hex of the raw token (64 chars).
            sa.Column("token_hash", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "expires_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
            ),
            # NULL = unconsumed; non-NULL = already used (single-use).
            sa.Column(
                "used_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
            ),
        )

    if not has_index("password_reset_tokens", "ix_prt_user_used_expires"):
        op.create_index(
            "ix_prt_user_used_expires",
            "password_reset_tokens",
            ["user_id", "used_at", "expires_at"],
        )


def downgrade() -> None:
    from migrations._helpers import has_index, has_table

    if has_index("password_reset_tokens", "ix_prt_user_used_expires"):
        op.drop_index("ix_prt_user_used_expires", table_name="password_reset_tokens")

    if has_table("password_reset_tokens"):
        op.drop_table("password_reset_tokens")
