from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID
import uuid


from backend.core.database import Base


class Anime(Base):

    __tablename__ = 'anime'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String(200), nullable=False, index=True)
    episodes = Column(Integer, default=0)
    rating = Column(Float, default=0.0)
    status = Column(String(20), default='finished')
    release_date = Column(DateTime, default=datetime.now)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=datetime.now)
    api_url = Column(String(200), nullable=False)

    voice_acting = Column(String(20), nullable=False)
    type = Column(String(20), nullable=False)



    def __repr__(self):
        return f'<Anime(id={self.id}, title={self.title})>'


class Review(Base):
    __tablename__ = 'reviews'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    text = Column(String(1500), nullable=False)
    anime_title = Column(String(200), nullable=False)
    anime_id = Column(Integer, ForeignKey('anime.id'), nullable=False)
    anime_rating = Column(Float, default=0.0)



class news(Base):
    __tablename__ = 'news'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)