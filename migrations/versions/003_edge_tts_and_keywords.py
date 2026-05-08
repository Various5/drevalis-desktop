"""Edge TTS provider, keyword overlays, and image quality boost.

Revision ID: 003
Revises: 002
Create Date: 2026-03-24
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    # voice_profiles: add edge_voice_id column
    if not has_column("voice_profiles", "edge_voice_id"):
        op.add_column("voice_profiles", sa.Column("edge_voice_id", sa.Text(), nullable=True))

    # Update provider check constraint to include 'edge'
    # Use raw SQL since constraint name varies between naming conventions
    op.execute("""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN (
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'voice_profiles'::regclass
                AND contype = 'c'
                AND pg_get_constraintdef(oid) LIKE '%provider%'
            ) LOOP
                EXECUTE 'ALTER TABLE voice_profiles DROP CONSTRAINT ' || quote_ident(r.conname);
            END LOOP;
        END $$;
    """)
    op.execute("""
        ALTER TABLE voice_profiles ADD CONSTRAINT ck_voice_profiles_provider_valid
        CHECK (provider IN ('piper', 'elevenlabs', 'kokoro', 'edge'))
    """)

    # series: add negative_prompt column
    if not has_column("series", "negative_prompt"):
        op.add_column("series", sa.Column("negative_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if has_column("series", "negative_prompt"):
        op.drop_column("series", "negative_prompt")

    op.execute("""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN (
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'voice_profiles'::regclass
                AND contype = 'c'
                AND pg_get_constraintdef(oid) LIKE '%provider%'
            ) LOOP
                EXECUTE 'ALTER TABLE voice_profiles DROP CONSTRAINT ' || quote_ident(r.conname);
            END LOOP;
        END $$;
    """)
    op.execute("""
        ALTER TABLE voice_profiles ADD CONSTRAINT ck_voice_profiles_provider_valid
        CHECK (provider IN ('piper', 'elevenlabs', 'kokoro'))
    """)

    if has_column("voice_profiles", "edge_voice_id"):
        op.drop_column("voice_profiles", "edge_voice_id")
