"""One-time password reset and persistent session invalidation."""
from alembic import op
import sqlalchemy as sa

revision = "0005_password_reset"
down_revision = "0004_email_verification"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("password_resets",
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("grant_digest", sa.String(64), nullable=True),
        sa.Column("grant_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("grant_digest", name="uq_password_reset_grant"),
        sa.CheckConstraint("attempts >= 0 AND attempts <= 5", name="ck_password_reset_attempts"))


def downgrade():
    op.drop_table("password_resets")
    op.drop_column("users", "auth_version")
