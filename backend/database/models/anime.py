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
    api_url = Column(String(200), nullable=False)
    #reviews = Column(Integer, default=0)

    # отношения

    #reviews = relationship("Review", back_populates="anime")

    def __repr__(self):
        return f'<Anime(id={self.id}, api_url={self.api_url})>'


class Review(Base):
    __tablename__ = 'reviews'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    text = Column(String(1500), nullable=False)
    anime_title = Column(String(200), nullable=False)
    anime_id = Column(UUID(as_uuid=True), ForeignKey('anime.id'), nullable=False)
    anime_rating = Column(Float, default=0.0)
    date = Column(DateTime, default=datetime.now)

    # Отношения
    #user = relationship("User", back_populates="reviews")
    #anime = relationship("Anime", back_populates="reviews")

class news(Base):
    __tablename__ = 'news'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)