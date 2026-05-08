"""TOTP 2FA columns on users.

Adds four columns to the ``users`` table that together implement
TOTP-based two-factor authentication:

* ``totp_secret_encrypted``      — Fernet-encrypted TOTP shared secret
                                   (RFC 6238 base32, 20 bytes).  NULL when
                                   2FA has never been enrolled.
* ``totp_key_version``           — Fernet key version used to encrypt the
                                   secret, following the versioned-key
                                   convention from migration 044.
* ``totp_confirmed_at``          — Timestamp set when the user first
                                   successfully verifies a code after
                                   enrolment.  Login enforcement gates on
                                   this column (``IS NOT NULL``), not on the
                                   presence of the secret, so a half-finished
                                   enrolment never locks users out.
* ``totp_recovery_codes_encrypted`` — Fernet-encrypted JSON list of one-time
                                       recovery codes (10 × 16 hex chars).
                                       NULL until enrolment completes.
                                       Codes are consumed in-place (the list
                                       shrinks by one on each use).

No backfill is required — all columns are nullable and default NULL.

Revision ID: 045
Revises: 044
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "045"
down_revision: str | None = "044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column

    if not has_column("users", "totp_secret_encrypted"):
        op.add_column(
            "users",
            sa.Column("totp_secret_encrypted", sa.Text(), nullable=True),
        )

    if not has_column("users", "totp_key_version"):
        op.add_column(
            "users",
            sa.Column("totp_key_version", sa.Integer(), nullable=True),
        )

    if not has_column("users", "totp_confirmed_at"):
        op.add_column(
            "users",
            sa.Column(
                "totp_confirmed_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
            ),
        )

    if not has_column("users", "totp_recovery_codes_encrypted"):
        op.add_column(
            "users",
            sa.Column("totp_recovery_codes_encrypted", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    from migrations._helpers import has_column

    for col in (
        "totp_recovery_codes_encrypted",
        "totp_confirmed_at",
        "totp_key_version",
        "totp_secret_encrypted",
    ):
        if has_column("users", col):
            op.drop_column("users", col)
