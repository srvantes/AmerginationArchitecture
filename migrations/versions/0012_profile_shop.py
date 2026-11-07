"""Profile cosmetics, inventory and points ledger."""
from alembic import op
import sqlalchemy as sa

revision = "0012_profile_shop"
down_revision = "0011_discussion_replies_votes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_profiles", sa.Column("mini_profile_background", sa.String(255)))
    op.add_column("user_profiles", sa.Column("profile_theme", sa.String(40)))
    op.execute("UPDATE user_profiles SET mini_profile_background = profile_background "
               "WHERE profile_background <> '/static/default_background.jpg'")
    op.create_table(
        "point_events",
        sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("delta", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    items = op.create_table(
        "profile_shop_items",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("price", sa.Integer, nullable=False),
        sa.Column("asset", sa.String(160)),
        sa.CheckConstraint("price >= 0", name="ck_shop_item_price"),
        sa.CheckConstraint("kind IN ('profile_background', 'mini_profile_background', 'profile_theme')",
                           name="ck_shop_item_kind"),
    )
    op.bulk_insert(items, [
        {"id": "aurora", "kind": "profile_theme", "name": "Северное сияние", "price": 100},
        {"id": "twilight", "kind": "profile_theme", "name": "Сумерки", "price": 150},
        {"id": "ember", "kind": "profile_theme", "name": "Тлеющие угли", "price": 150},
    ])
    op.create_table(
        "profile_shop_ownership",
        sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("item_id", sa.String(40), sa.ForeignKey("profile_shop_items.id"), primary_key=True),
    )


def downgrade():
    op.drop_table("profile_shop_ownership")
    op.drop_table("profile_shop_items")
    op.drop_table("point_events")
    op.drop_column("user_profiles", "profile_theme")
    op.drop_column("user_profiles", "mini_profile_background")
