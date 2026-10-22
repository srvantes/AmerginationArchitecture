from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from backend.core.database import Base


class PasswordReset(Base):
    __tablename__ = "password_resets"
    __table_args__ = (CheckConstraint("attempts >= 0 AND attempts <= 5", name="ck_password_reset_attempts"),)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    code_digest = Column(String(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    grant_digest = Column(String(64), nullable=True, unique=True)
    grant_expires_at = Column(DateTime(timezone=True), nullable=True)
