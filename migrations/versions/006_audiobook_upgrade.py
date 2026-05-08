"""Add chapters, multi-voice, background music, output formats, and audio controls to audiobooks.

Revision ID: 006
Revises: 005
Create Date: 2026-03-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('audiobooks', sa.Column('output_format', sa.Text(), server_default='audio_only', nullable=False))
    op.add_column('audiobooks', sa.Column('cover_image_path', sa.Text(), nullable=True))
    op.add_column('audiobooks', sa.Column('chapters', JSONB(), nullable=True))
    op.add_column('audiobooks', sa.Column('voice_casting', JSONB(), nullable=True))
    op.add_column('audiobooks', sa.Column('music_enabled', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('audiobooks', sa.Column('music_mood', sa.Text(), nullable=True))
    op.add_column('audiobooks', sa.Column('music_volume_db', sa.Numeric(), server_default='-14.0', nullable=False))
    op.add_column('audiobooks', sa.Column('speed', sa.Numeric(), server_default='1.0', nullable=False))
    op.add_column('audiobooks', sa.Column('pitch', sa.Numeric(), server_default='1.0', nullable=False))
    op.add_column('audiobooks', sa.Column('mp3_path', sa.Text(), nullable=True))

    op.create_check_constraint(
        'ck_audiobooks_output_format',
        'audiobooks',
        "output_format IN ('audio_only', 'audio_image', 'audio_video')"
    )


def downgrade() -> None:
    op.drop_constraint('ck_audiobooks_output_format', 'audiobooks', type_='check')
    op.drop_column('audiobooks', 'mp3_path')
    op.drop_column('audiobooks', 'pitch')
    op.drop_column('audiobooks', 'speed')
    op.drop_column('audiobooks', 'music_volume_db')
    op.drop_column('audiobooks', 'music_mood')
    op.drop_column('audiobooks', 'music_enabled')
    op.drop_column('audiobooks', 'voice_casting')
    op.drop_column('audiobooks', 'chapters')
    op.drop_column('audiobooks', 'cover_image_path')
    op.drop_column('audiobooks', 'output_format')
