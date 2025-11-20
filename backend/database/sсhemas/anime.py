from typing import List, Optional


from pydantic import BaseModel, Field
from datetime import datetime


### ======== BASE SHEMAS ======== ###
class BaseGenre(BaseModel):
    name: Optional[str] = Field(..., min_length=1, max_length=50)


class BaseAnime(BaseModel):
    title: Optional[str] = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    episodes: Optional[int] = Field(None, ge=0)
    seasons: Optional[int] = Field(None, ge=0)
    status: Optional[str] = Field('ongoing', regex='^(ongoing|completed|announced)$')
    release_date: Optional[datetime.year] = Field(None, ge=0)
    rating: Optional[float] = Field(ge=0, le=10, description="Rating must be between 0 and 10")

class BaseReviews(BaseModel):
    text: str = Field(..., min_length=1, max_length=6000)
    rating: Optional[float] = Field(ge=0, le=10)
    anime_title: Optional[str] = Field(None, min_length=1, max_length=50)


### ======== CREATE SHEMAS ======== ###
#(without id)
class CreateGenre(BaseGenre):
    pass

class CreateAnime(BaseAnime):
    genres: List[CreateGenre] = []

class CreateReview(BaseReviews):
    anime_id: int




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




