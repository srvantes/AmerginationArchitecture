from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field
from typing import List



class BaseBadge(BaseModel):

    name: str
    description: Optional[str] = None
    icon_url: Optional[str] = None
    rarity: str

class Badge(BaseBadge):
    id: int

    class Config:
        from_attributes = True



class BaseUser(BaseModel):

    nickname: str = Field(..., min_length=3, max_length=40)
    email: EmailStr
    avatar_url: Optional[str] = None
    custom_url: Optional[str] = Field(None, regex=r"^[a-zA-Z0-9_-]+$")


class UserCreate(BaseUser):
    password: str = Field(..., min_length=8)



class UserUpdate(BaseModel):
    username: Optional[str] = None
    bio: Optional[str] = None
    country: Optional[str] = None
    show_username: Optional[bool] = None
    avatar_url: Optional[str] = None
    profile_background: Optional[str] = None


class UserProfile(BaseUser):
    id: int
    real_name: Optional[str] = None
    bio: Optional[str] = None
    country: Optional[str] = None
    status: str
    anime_watched: int
    reviews_written: int
    role: str
    is_verified: bool
    is_premium: bool
    badges: List[Badge] = []
    created_at: datetime
    last_online: datetime

    class Config():
        from_attributes = True

class UserAdmin(UserProfile):
    email: EmailStr
    show_username: bool
    show_watchlist: bool


class UserStats(BaseModel):
    total_users: int
    online_users: int
    new_today: int

    