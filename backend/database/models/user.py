from sqlalchemy import Table, Column, Integer, String, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.core.database import Base
from sqlalchemy.dialects.postgresql import UUID

import uuid


class User(Base):
    __tablename__ = "users"


    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(100), nullable=False)

    avatar_url = Column(String(255), default="/static/default_avatar.jpg")
    profile_background = Column(String(255), default="/static/default_background.jpg")
    status = Column(String(20), default='online')
    custom_url = Column(String(255), unique=True)
    nickname = Column(String(100))
    country = Column(String(100))
    bio = Column(Text)


    #Statistic

    anime_watched = Column(Integer, default=0)
    reviews_written = Column(Integer, default=0)

    role = Column(String(20), default='user') # user, moder, admin
    is_verified = Column(Boolean, default=False)
    is_premium = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    show_watchlist = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now())
    last_online = Column(DateTime, server_default=func.now())


    # Relationships

#    review = relationship("Review", back_populates="user")
#    anime = relationship("Anime", back_populates="user")


    def __repr__(self):
        return f"<User {self.username}>"


class UserBadge(Base):
    __tablename__ = "user_badges"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    badge_id = Column(Integer, ForeignKey("badges.id"))


class Badge(Base):
    __tablename__ = "badges"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    icon_url = Column(String(255))
    rarity = Column(String(20)) # пока не знаю какие редкости сделать




class UserProfile(Base):
    __tablename__ = "user_profiles"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))