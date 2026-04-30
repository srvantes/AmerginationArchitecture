from datetime import datetime
from typing import Optional
from uuid import UUID

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
    username: str = Field(..., min_length=3, max_length=40)
    email: EmailStr



class UserCreate(BaseUser):
    password: str = Field(..., min_length=8)

class UserOut(BaseModel):
    id: UUID
    username: str
    email: EmailStr
    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    username: str
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    username: Optional[str] = None
    bio: Optional[str] = None
    country: Optional[str] = None
    show_nickname: Optional[bool] = None
    avatar_url: Optional[str] = None
    profile_background: Optional[str] = None


class UserProfile(BaseUser):
    id: UUID
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
    avatar_url: Optional[str] = None
    custom_url: Optional[str] = Field(None, pattern=r"^[a-zA-Z0-9_-]+$")

    class Config():
        from_attributes = True


class UserStats(BaseModel):
    total_users: int
    online_users: int
    new_today: int

class UserInDB(BaseUser):
    hashed_password: str
    id: int
    created_at: datetime
    last_online: datetime
    role: str = "user"

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    user_id: Optional[int] = None
    nickname: Optional[str] = None