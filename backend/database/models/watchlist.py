import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from backend.core.database import Base


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "anime_source", "anime_external_id", name="uq_watchlist_user_anime"),
        CheckConstraint("episodes_watched >= 0", name="ck_watchlist_progress"),
        CheckConstraint("status IN ('planned', 'watching', 'completed', 'on_hold', 'dropped')", name="ck_watchlist_status"),
        CheckConstraint("anime_source IN ('shikimori', 'animego', 'kodik')", name="ck_watchlist_source"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    anime_source = Column(String(30), nullable=False, default="shikimori", server_default="shikimori")
    anime_external_id = Column(String(100), nullable=False)
    anime_title = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False, default="planned", server_default="planned")
    episodes_watched = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
