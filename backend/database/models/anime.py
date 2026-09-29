from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "anime_source",
            "anime_external_id",
            name="uq_review_user_anime",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    anime_source = Column(
        String(30), nullable=False, default="shikimori", server_default="shikimori"
    )
    anime_external_id = Column(String(100), nullable=False, index=True)
    anime_title = Column(String(200), nullable=False)
    text = Column(String(6000), nullable=False)
    anime_rating = Column(Float, nullable=True)
    date = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="reviews")
