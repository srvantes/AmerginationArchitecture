"""Permanent achievements and a user-selected public showcase."""
from alembic import op
import sqlalchemy as sa

revision = "0007_achievements"
down_revision = "0006_watchlist_posters"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("user_achievements",
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("showcase_slot", sa.Integer(), nullable=True),
        sa.CheckConstraint("code IN ('email_verified','first_anime','ten_anime','eleven_likes','first_review')", name="ck_achievement_code"),
        sa.CheckConstraint("showcase_slot IS NULL OR showcase_slot BETWEEN 1 AND 4", name="ck_achievement_slot"),
        sa.UniqueConstraint("user_id", "showcase_slot", name="uq_achievement_showcase_slot"))


def downgrade():
    op.drop_table("user_achievements")
