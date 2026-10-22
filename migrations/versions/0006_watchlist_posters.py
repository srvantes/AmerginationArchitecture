"""Store watchlist posters and AnimeGo navigation slugs."""
from alembic import op
import sqlalchemy as sa

revision = "0006_watchlist_posters"
down_revision = "0005_password_reset"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("watchlist_entries", sa.Column("poster_url", sa.String(2048), nullable=True))
    op.add_column("watchlist_entries", sa.Column("anime_slug", sa.String(300), nullable=True))


def downgrade():
    op.drop_column("watchlist_entries", "anime_slug")
    op.drop_column("watchlist_entries", "poster_url")
