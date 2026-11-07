from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from .achievement import AchievementOut


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
    email: EmailStr = Field(..., max_length=100)


class UserCreate(BaseUser):
    username: str = Field(..., min_length=3, max_length=40, pattern=r"\S")
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.lower()


class UserOut(BaseUser):
    id: UUID
    email_verified: bool


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
    mini_profile_background: str | None = None
    profile_theme: str | None = None
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
    can_write_reviews: bool
    created_at: datetime
    last_online: datetime


class UserMe(BaseUser):
    id: UUID
    email_verified: bool
    profile: UserProfile


class PublicProfile(BaseModel):
    id: UUID
    username: str
    nickname: str | None = None
    avatar_url: str | None = None
    profile_background: str | None = None
    mini_profile_background: str | None = None
    profile_theme: str | None = None
    country: str | None = None
    bio: str | None = None
    created_at: datetime
    show_watchlist: bool


class MiniProfile(BaseModel):
    profile: PublicProfile
    achievements: list[AchievementOut]


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


class EmailCode(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$", strict=True)


class UserProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    avatar_url: str | None = Field(None, max_length=255)
    status: str | None = Field(None, max_length=20)
    custom_url: str | None = Field(None, pattern=r"^[a-zA-Z0-9_-]+$", max_length=50)
    nickname: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    bio: str | None = Field(None, max_length=1000)
    show_watchlist: bool | None = None

    @field_validator("nickname", "country", "bio")
    @classmethod
    def empty_to_none(cls, value):
        return value or None

    @model_validator(mode="before")
    @classmethod
    def reject_null_required_fields(cls, data):
        if isinstance(data, dict) and any(key in data and data[key] is None for key in ("status", "show_watchlist")):
            raise ValueError("Status and visibility cannot be null")
        return data
