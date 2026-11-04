from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from backend.core.database import Base


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    __table_args__ = (
        CheckConstraint("code IN ('email_verified','first_anime','ten_anime','eleven_likes','first_review')", name="ck_achievement_code"),
        CheckConstraint("showcase_slot IS NULL OR showcase_slot BETWEEN 1 AND 4", name="ck_achievement_slot"),
        UniqueConstraint("user_id", "showcase_slot", name="uq_achievement_showcase_slot"),
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    code = Column(String(40), primary_key=True)
    awarded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    showcase_slot = Column(Integer, nullable=True)
