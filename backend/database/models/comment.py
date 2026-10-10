import uuid
from sqlalchemy import Column, DateTime, ForeignKey, String, Text, Boolean, Index, func
from sqlalchemy.dialects.postgresql import UUID
from backend.core.database import Base


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_anime_date", "anime_source", "anime_external_id", "created_at"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    anime_source = Column(String(30), nullable=False)
    anime_external_id = Column(String(100), nullable=False)
    text = Column(Text, nullable=False)
    has_spoilers = Column(Boolean, nullable=False, server_default="false", default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CommentLike(Base):
    __tablename__ = "comment_likes"
    comment_id = Column(UUID(as_uuid=True), ForeignKey("comments.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
