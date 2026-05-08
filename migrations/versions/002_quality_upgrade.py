"""Quality upgrade -- caption styles, music, video workflows, kokoro TTS.

Adds columns to ``series`` and ``voice_profiles`` tables for:
- Phase 1: Caption animation styles (JSONB on series)
- Phase 3: Background music configuration (series)
- Phase 4: Video ComfyUI workflow FK (series)
- Phase 5: Kokoro TTS provider support (voice_profiles)

Revision ID: 002
Revises: 001
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── series table additions ────────────────────────────────────────
    op.add_column(
        "series",
        sa.Column("caption_style", JSONB, nullable=True),
    )
    op.add_column(
        "series",
        sa.Column("music_mood", sa.Text(), nullable=True),
    )
    op.add_column(
        "series",
        sa.Column(
            "music_volume_db",
            sa.Numeric(),
            nullable=True,
            server_default="14.0",
        ),
    )
    op.add_column(
        "series",
        sa.Column(
            "music_enabled",
            sa.Boolean(),
            nullable=True,
            server_default="true",
        ),
    )
    op.add_column(
        "series",
        sa.Column(
            "video_comfyui_workflow_id",
            UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_series_video_workflow",
        "series",
        "comfyui_workflows",
        ["video_comfyui_workflow_id"],
        ["id"],
    )

    # ── voice_profiles table additions ────────────────────────────────
    op.add_column(
        "voice_profiles",
        sa.Column("kokoro_voice_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "voice_profiles",
        sa.Column("kokoro_model_path", sa.Text(), nullable=True),
    )

    # Update provider check constraint to include 'kokoro'
    op.drop_constraint(
        "ck_voice_profiles_provider_valid",
        "voice_profiles",
    )
    op.create_check_constraint(
        "ck_voice_profiles_provider_valid",
        "voice_profiles",
        "provider IN ('piper', 'elevenlabs', 'kokoro')",
    )


def downgrade() -> None:
    # ── Revert voice_profiles changes ─────────────────────────────────
    # Restore original provider constraint (without 'kokoro')
    op.drop_constraint(
        "ck_voice_profiles_provider_valid",
        "voice_profiles",
    )
    op.create_check_constraint(
        "ck_voice_profiles_provider_valid",
        "voice_profiles",
        "provider IN ('piper', 'elevenlabs')",
    )

    op.drop_column("voice_profiles", "kokoro_model_path")
    op.drop_column("voice_profiles", "kokoro_voice_name")

    # ── Revert series changes ─────────────────────────────────────────
    op.drop_constraint("fk_series_video_workflow", "series", type_="foreignkey")
    op.drop_column("series", "video_comfyui_workflow_id")
    op.drop_column("series", "music_enabled")
    op.drop_column("series", "music_volume_db")
    op.drop_column("series", "music_mood")
    op.drop_column("series", "caption_style")
