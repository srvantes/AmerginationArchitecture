"""Email ownership confirmation.
Revision ID: 0004_email_verification
Revises: 0003_discussion
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_email_verification"
down_revision = "0003_discussion"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("email_verifications",
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint("attempts >= 0 AND attempts <= 5", name="ck_email_verification_attempts"))


def downgrade():
    op.drop_table("email_verifications")
    op.drop_column("users", "email_verified_at")
