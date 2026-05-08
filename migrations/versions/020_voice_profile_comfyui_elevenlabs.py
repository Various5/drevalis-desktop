"""Extend voice_profiles.provider CHECK to include comfyui_elevenlabs.

Migration 003 added the ``ck_voice_profiles_provider_valid`` check with
the then-supported set ``{piper, elevenlabs, kokoro, edge}``. Since
then, a fifth provider — ``comfyui_elevenlabs`` (ElevenLabs routed via
a ComfyUI workflow) — was added to the ORM model's CheckConstraint
but no migration updated the database-side constraint. Inserting a
row with that value, including during a restore from backup, now
fails with CheckViolationError.

Drop the old constraint, re-create it with the full five-value set.

Revision ID: 020
Revises: 019
Create Date: 2026-04-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PROVIDERS_OLD = "'piper', 'elevenlabs', 'kokoro', 'edge'"
_PROVIDERS_NEW = "'piper', 'elevenlabs', 'kokoro', 'edge', 'comfyui_elevenlabs'"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE voice_profiles DROP CONSTRAINT IF EXISTS ck_voice_profiles_provider_valid"
    )
    op.execute(
        f"ALTER TABLE voice_profiles ADD CONSTRAINT ck_voice_profiles_provider_valid "
        f"CHECK (provider IN ({_PROVIDERS_NEW}))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE voice_profiles DROP CONSTRAINT IF EXISTS ck_voice_profiles_provider_valid"
    )
    op.execute(
        f"ALTER TABLE voice_profiles ADD CONSTRAINT ck_voice_profiles_provider_valid "
        f"CHECK (provider IN ({_PROVIDERS_OLD}))"
    )
