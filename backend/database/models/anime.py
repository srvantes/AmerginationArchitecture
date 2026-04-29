from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from datetime import datetime
from sqlalchemy.orm import relationship
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
    #reviews = Column(Integer, default=0)

    voice_acting = Column(String(20), nullable=False)
    type = Column(String(20), nullable=False)

    # отношения

    #reviews = relationship("Review", back_populates="anime")

    def __repr__(self):
        return f'<Anime(id={self.id}, title={self.title})>'


class Review(Base):
    __tablename__ = 'reviews'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    text = Column(String(1500), nullable=False)
    anime_title = Column(String(200), nullable=False)
    anime_id = Column(Integer, ForeignKey('anime.id'), nullable=False)
    anime_rating = Column(Float, default=0.0)
    date = Column(DateTime, default=datetime.now)

    # Отношения
    #user = relationship("User", back_populates="reviews")
    #anime = relationship("Anime", back_populates="reviews")

class news(Base):
    __tablename__ = 'news'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)