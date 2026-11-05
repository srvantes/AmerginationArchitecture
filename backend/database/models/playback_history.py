"""A private last-opened player selection, independent of watched progress."""
import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from backend.core.database import Base


class PlaybackHistory(Base):
    __tablename__ = "playback_history"
    __table_args__ = (
        UniqueConstraint("user_id", "anime_source", "anime_external_id", name="uq_playback_history_user_anime"),
        CheckConstraint("anime_source IN ('shikimori', 'animego')", name="ck_playback_history_source"),
        CheckConstraint("player IN ('aniboom', 'kodik', 'cvh', 'sibnet')", name="ck_playback_history_player"),
        CheckConstraint("episode BETWEEN 1 AND 100000", name="ck_playback_history_episode"),
        Index("ix_playback_history_user_updated", "user_id", "updated_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    anime_source = Column(String(20), nullable=False)
    anime_external_id = Column(String(20), nullable=False)
    anime_title = Column(String(200), nullable=False)
    poster_url = Column(String(2048), nullable=True)
    anime_slug = Column(String(300), nullable=True)
    episode = Column(Integer, nullable=False)
    player = Column(String(20), nullable=False)
    translation_id = Column(String(20), nullable=False)
    translation_source = Column(String(20), nullable=False, default="animego", server_default="animego")
    translation_name = Column(String(200), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
