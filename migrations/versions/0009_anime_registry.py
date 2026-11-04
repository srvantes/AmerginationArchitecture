"""Persistent title identities and public slugs, independent of Redis expiry."""
from alembic import op
import sqlalchemy as sa


revision = "0009_anime_registry"
down_revision = "0008_playback_history"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("anime_registry",
        sa.Column("source", sa.String(20), primary_key=True),
        sa.Column("external_id", sa.String(20), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("original_title", sa.Text(), nullable=True),
        sa.Column("public_slug", sa.String(300), nullable=False),
        sa.Column("upstream_slug", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source IN ('shikimori', 'animego')", name="ck_anime_registry_source"),
        sa.CheckConstraint("length(public_slug) > 0", name="ck_anime_registry_slug"))


def downgrade():
    op.drop_table("anime_registry")
