from sqlalchemy import CheckConstraint, Column, DateTime, String, Text, func

from backend.core.database import Base


class AnimeRegistry(Base):
    __tablename__ = "anime_registry"
    __table_args__ = (
        CheckConstraint("source IN ('shikimori', 'animego')", name="ck_anime_registry_source"),
        CheckConstraint("length(public_slug) > 0", name="ck_anime_registry_slug"),
    )

    source = Column(String(20), primary_key=True)
    external_id = Column(String(20), primary_key=True)
    title = Column(Text, nullable=False)
    original_title = Column(Text, nullable=True)
    public_slug = Column(String(300), nullable=False)
    upstream_slug = Column(String(300), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
