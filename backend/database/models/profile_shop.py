from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Uuid, func

from backend.core.database import Base


class PointEvent(Base):
    __tablename__ = "point_events"

    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key = Column(String(200), primary_key=True)
    delta = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProfileShopItem(Base):
    __tablename__ = "profile_shop_items"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_shop_item_price"),
        CheckConstraint("kind IN ('profile_background', 'mini_profile_background', 'profile_theme')",
                        name="ck_shop_item_kind"),
    )

    id = Column(String(40), primary_key=True)
    kind = Column(String(24), nullable=False)
    name = Column(String(100), nullable=False)
    price = Column(Integer, nullable=False)
    asset = Column(String(160))


class ProfileShopOwnership(Base):
    __tablename__ = "profile_shop_ownership"

    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    item_id = Column(String(40), ForeignKey("profile_shop_items.id"), primary_key=True)
