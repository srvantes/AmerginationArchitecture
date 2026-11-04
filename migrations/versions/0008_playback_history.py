"""Private last-opened player selections, separate from watched progress."""
from alembic import op
import sqlalchemy as sa


revision = "0008_playback_history"
down_revision = "0007_achievements"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("playback_history",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("anime_source", sa.String(20), nullable=False),
        sa.Column("anime_external_id", sa.String(20), nullable=False),
        sa.Column("anime_title", sa.String(200), nullable=False),
        sa.Column("poster_url", sa.String(2048), nullable=True),
        sa.Column("anime_slug", sa.String(300), nullable=True),
        sa.Column("episode", sa.Integer(), nullable=False),
        sa.Column("player", sa.String(20), nullable=False),
        sa.Column("translation_id", sa.String(20), nullable=False),
        sa.Column("translation_name", sa.String(200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "anime_source", "anime_external_id", name="uq_playback_history_user_anime"),
        sa.CheckConstraint("anime_source IN ('shikimori', 'animego')", name="ck_playback_history_source"),
        sa.CheckConstraint("player IN ('aniboom', 'kodik', 'cvh', 'sibnet')", name="ck_playback_history_player"),
        sa.CheckConstraint("episode BETWEEN 1 AND 100000", name="ck_playback_history_episode"))
    op.create_index("ix_playback_history_user_updated", "playback_history", ["user_id", "updated_at"])


def downgrade():
    op.drop_index("ix_playback_history_user_updated", table_name="playback_history")
    op.drop_table("playback_history")
