"""Widen ``media_assets.asset_type`` CHECK + add ``(episode_id, scene_number)`` index.

The original CHECK constraint from migration 001 allowed only six
``asset_type`` values. Code paths added since then write three more —
``scene_image`` (music-video orchestrator), ``scene_video`` (video-mode
pipeline), and ``video_proxy`` (edit-session proxy renders) — which the
DB rejects with an integrity error. The ORM enum is already updated;
this migration brings the DB constraint in line.

Also adds ``ix_media_assets_episode_id_scene_number`` so per-scene
regen lookups stop scanning the full per-episode asset list.

Revision ID: 036
Revises: 035
Create Date: 2026-04-29
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "036"
down_revision: str | None = "035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_VALUES = (
    "'voiceover', 'scene', 'scene_image', 'scene_video', "
    "'caption', 'video', 'video_proxy', 'thumbnail', 'temp'"
)
_OLD_VALUES = "'voiceover', 'scene', 'caption', 'video', 'thumbnail', 'temp'"


def upgrade() -> None:
    from migrations._helpers import has_index

    op.execute("ALTER TABLE media_assets DROP CONSTRAINT IF EXISTS asset_type_valid")
    op.execute("ALTER TABLE media_assets DROP CONSTRAINT IF EXISTS ck_media_assets_asset_type_valid")
    op.create_check_constraint(
        "asset_type_valid",
        "media_assets",
        f"asset_type IN ({_NEW_VALUES})",
    )

    if not has_index("media_assets", "ix_media_assets_episode_id_scene_number"):
        op.create_index(
            "ix_media_assets_episode_id_scene_number",
            "media_assets",
            ["episode_id", "scene_number"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_media_assets_episode_id_scene_number",
        table_name="media_assets",
    )
    op.execute("ALTER TABLE media_assets DROP CONSTRAINT IF EXISTS asset_type_valid")
    op.create_check_constraint(
        "asset_type_valid",
        "media_assets",
        f"asset_type IN ({_OLD_VALUES})",
    )
