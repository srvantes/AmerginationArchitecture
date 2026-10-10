"""Comments, likes and earned review access.

Revision ID: 0003_discussion
Revises: 0002_watchlist
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_discussion"
down_revision = "0002_watchlist"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_profiles", sa.Column("can_write_reviews", sa.Boolean(), server_default=sa.false(), nullable=False))
    with op.batch_alter_table("reviews") as batch:
        batch.add_column(sa.Column("title", sa.String(200), server_default="Рецензия", nullable=False))
        batch.add_column(sa.Column("has_spoilers", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.alter_column("text", existing_type=sa.String(6000), type_=sa.Text(), existing_nullable=False)
    op.create_index("ix_reviews_anime_date", "reviews", ["anime_source", "anime_external_id", "date"])
    op.create_table("comments",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("anime_source", sa.String(30), nullable=False),
        sa.Column("anime_external_id", sa.String(100), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("has_spoilers", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_comments_user_id", "comments", ["user_id"])
    op.create_index("ix_comments_anime_date", "comments", ["anime_source", "anime_external_id", "created_at"])
    op.create_table("comment_likes",
        sa.Column("comment_id", sa.UUID(), sa.ForeignKey("comments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True))


def downgrade():
    op.drop_table("comment_likes")
    op.drop_table("comments")
    op.drop_index("ix_reviews_anime_date", table_name="reviews")
    with op.batch_alter_table("reviews") as batch:
        batch.drop_column("has_spoilers")
        batch.drop_column("title")
        batch.alter_column("text", existing_type=sa.Text(), type_=sa.String(6000), existing_nullable=False)
    op.drop_column("user_profiles", "can_write_reviews")
