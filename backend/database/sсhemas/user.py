from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class BaseBadge(BaseModel):
    name: str
    description: str | None = None
    icon_url: str | None = None
    rarity: str


class Badge(BaseBadge):
    model_config = ConfigDict(from_attributes=True)
    id: int


class BaseUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    username: str = Field(..., min_length=3, max_length=40)
    email: EmailStr


class UserCreate(BaseUser):
    password: str = Field(..., min_length=8, max_length=128)


class UserOut(BaseUser):
    id: UUID


class UserLogin(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)


class UserUpdate(BaseModel):
    username: str | None = Field(None, min_length=3, max_length=40)


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    avatar_url: str | None = None
    profile_background: str | None = None
    status: str
    custom_url: str | None = None
    nickname: str | None = None
    country: str | None = None
    bio: str | None = None
    anime_watched: int
    reviews_written: int
    role: str
    is_verified: bool
    is_premium: bool
    is_active: bool
    show_watchlist: bool
    created_at: datetime
    last_online: datetime


class UserMe(BaseUser):
    id: UUID
    profile: UserProfile


class UserStats(BaseModel):
    total_users: int
    online_users: int
    new_today: int


class UserInDB(BaseUser):
    id: UUID
    hashed_password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: UUID | None = None


class UserProfileUpdate(BaseModel):
    avatar_url: str | None = None
    profile_background: str | None = None
    status: str | None = Field(None, max_length=20)
    custom_url: str | None = Field(None, pattern=r"^[a-zA-Z0-9_-]+$", max_length=50)
    nickname: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    bio: str | None = Field(None, max_length=1000)
    show_watchlist: bool | None = None
