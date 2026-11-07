"""Reply relationships and mutually exclusive reactions."""
from alembic import op
import sqlalchemy as sa

revision = "0011_discussion_replies_votes"
down_revision = "0010_playback_translation_source"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().dialect.name == "sqlite":
        op.execute("ALTER TABLE comments ADD COLUMN parent_id CHAR(32) REFERENCES comments(id) ON DELETE SET NULL")
    else:
        op.add_column("comments", sa.Column("parent_id", sa.UUID(), sa.ForeignKey(
            "comments.id", ondelete="SET NULL", name="fk_comments_parent")))
    op.create_index("ix_comments_parent_id", "comments", ["parent_id"])
    with op.batch_alter_table("comment_likes") as batch:
        batch.add_column(sa.Column("value", sa.SmallInteger(), nullable=False, server_default="1"))
        batch.create_check_constraint("ck_comment_reaction_value", "value IN (-1, 1)")
    op.create_table(
        "review_votes",
        sa.Column("review_id", sa.UUID(), sa.ForeignKey("reviews.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("value", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("value IN (-1, 1)", name="ck_review_reaction_value"),
    )


def downgrade():
    op.drop_table("review_votes")
    op.execute(sa.text("DELETE FROM comment_likes WHERE value = -1"))
    with op.batch_alter_table("comment_likes") as batch:
        batch.drop_constraint("ck_comment_reaction_value", type_="check")
        batch.drop_column("value")
    op.drop_index("ix_comments_parent_id", table_name="comments")
    if op.get_context().dialect.name != "sqlite":
        op.drop_constraint("fk_comments_parent", "comments", type_="foreignkey")
    op.drop_column("comments", "parent_id")
