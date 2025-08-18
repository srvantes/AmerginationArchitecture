from typing import List
from pydantic import BaseModel, Field
from people import User


class Genre(BaseModel):
    name: str


class Anime(BaseModel):
    title: str
    id: str
    api: ...
    genres: List[Genre]
    review: List[str]
    status: str
    rating: float = Field(ge=0, le=10, description="Rating must be between 0 and 10")

class Reviews(BaseModel):
    user_id: str
    anime_id: str
    username: User.nickname
    text: str = Field(..., description="Review text")
