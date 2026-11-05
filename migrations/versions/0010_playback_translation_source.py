"""Distinguish direct provider translations from legacy AnimeGo IDs."""
from alembic import op
import sqlalchemy as sa

revision = "0010_playback_translation_source"
down_revision = "0009_anime_registry"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("playback_history", sa.Column("translation_source", sa.String(20),
                                               nullable=False, server_default="animego"))


def downgrade():
    op.drop_column("playback_history", "translation_source")
