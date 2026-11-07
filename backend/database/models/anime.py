from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.core.database import Base


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        Index("ix_reviews_anime_date", "anime_source", "anime_external_id", "date"),
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
    title = Column(String(200), nullable=False, server_default="Рецензия")
    text = Column(Text, nullable=False)
    has_spoilers = Column(Boolean, nullable=False, default=False, server_default="false")
    anime_rating = Column(Float, nullable=True)
    date = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="reviews", lazy="joined")

    @property
    def author_name(self):
        return self.user.username


class ReviewVote(Base):
    __tablename__ = "review_votes"
    __table_args__ = (CheckConstraint("value IN (-1, 1)", name="ck_review_reaction_value"),)

    review_id = Column(UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    value = Column(SmallInteger, nullable=False)
