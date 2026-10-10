"""Add user watchlists.

Revision ID: 0002_watchlist
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_watchlist"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("anime_source", sa.String(30), server_default="shikimori", nullable=False),
        sa.Column("anime_external_id", sa.String(100), nullable=False),
        sa.Column("anime_title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), server_default="planned", nullable=False),
        sa.Column("episodes_watched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "anime_source", "anime_external_id", name="uq_watchlist_user_anime"),
        sa.CheckConstraint("episodes_watched >= 0", name="ck_watchlist_progress"),
        sa.CheckConstraint(
            "status IN ('planned', 'watching', 'completed', 'on_hold', 'dropped')",
            name="ck_watchlist_status",
        ),
        sa.CheckConstraint("anime_source IN ('shikimori', 'animego', 'kodik')", name="ck_watchlist_source"),
    )
    op.create_index("ix_watchlist_entries_user_id", "watchlist_entries", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_entries_user_id", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
