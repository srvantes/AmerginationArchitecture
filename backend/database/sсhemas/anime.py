from typing import List, Optional
from uuid import UUID as PydanticUUID

from pydantic import BaseModel, Field
from datetime import datetime

from pydantic.v1 import UUID1

from backend.database.sсhemas.user import BaseUser


### ======== BASE SHEMAS ======== ###
class BaseGenre(BaseModel):
    name: Optional[str] = Field(..., min_length=1, max_length=50)


class BaseAnime(BaseModel):
    id: PydanticUUID
    title: Optional[str] = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    episodes: Optional[int] = Field(None, ge=0)
    seasons: Optional[int] = Field(None, ge=0)
    status: Optional[str] = Field(default='ongoing', pattern='^(ongoing|completed|announced)$')
    release_date: Optional[datetime] = Field(None)
    rating: Optional[float] = Field(None, ge=0, le=10, description="Rating must be between 0 and 10")
    api_url: Optional[str] = Field(None, min_length=1, max_length=200)

class BaseReviews(BaseModel):
    anime: BaseAnime
    user: BaseUser
    text: str = Field(..., min_length=1, max_length=6000)
    rating: Optional[float] = Field(None, ge=0, le=10)
    anime_title: Optional[str] = Field(None, min_length=1, max_length=50)
    date: Optional[datetime] = Field(None)


### ======== CREATE SHEMAS ======== ###
#(without id)
class CreateGenre(BaseGenre):
    class config:
        orm_mode = True

class CreateAnime(BaseAnime):
    genres: List[CreateGenre] = []

class CreateReview(BaseReviews):
    text: str
    rating: float | None = None


class UpdateReview(BaseReviews):
    text: Optional[str]

'''### ======== RESPONSE SHEMAS ======== ###

class Genre(BaseGenre):
    id: int

    class Config:
        from_attributes = True

class UserSimple(BaseModel):
    id: int
    username: str
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True


class Review(BaseReviews):
    id: int
    user: UserSimple
    crafted_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class Anime(BaseAnime):
    id: int
    genres: List[Genre] = []
    reviews: List[Review] = []
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
'''
class Wishlist(BaseModel):
    id: int




