from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.core.database import Base
from sqlalchemy.dialects.postgresql import UUID

import uuid


class User(Base):
    __tablename__ = "users"


    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    username = Column(String(40), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    auth_version = Column(Integer, nullable=False, default=0, server_default="0")

    @property
    def email_verified(self):
        return self.email_verified_at is not None




    # Relationships
    profile = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    reviews = relationship("Review", back_populates="user", cascade="all, delete-orphan")
#    review = relationship("Review", back_populates="user")
#    anime = relationship("Anime", back_populates="user")


    def __repr__(self):
        return f"<User {self.username}>"


class UserBadge(Base):
    __tablename__ = "user_badges"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
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
    id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    user = relationship("User", back_populates="profile")
    avatar_url = Column(String(255), default="/static/default_avatar.jpg")
    profile_background = Column(String(255), default="/static/default_background.jpg")
    status = Column(String(20), default="online", server_default="online", nullable=False)
    custom_url = Column(String(255), unique=True)
    nickname = Column(String(100))
    country = Column(String(100))
    bio = Column(Text)


    #Statistic

    anime_watched = Column(Integer, default=0, server_default="0", nullable=False)
    reviews_written = Column(Integer, default=0, server_default="0", nullable=False)

    role = Column(String(20), default="user", server_default="user", nullable=False)
    is_verified = Column(Boolean, default=False, server_default="false", nullable=False)
    is_premium = Column(Boolean, default=False, server_default="false", nullable=False)
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)

    show_watchlist = Column(Boolean, default=False, server_default="false", nullable=False)
    can_write_reviews = Column(Boolean, default=False, server_default="false", nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_online = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
