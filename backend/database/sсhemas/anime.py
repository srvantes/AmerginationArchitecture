from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from .discussion import validate_words


AnimeSource = Literal["shikimori", "animego", "kodik"]


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    anime_source: AnimeSource = "shikimori"
    anime_external_id: str = Field(..., min_length=1, max_length=100)
    anime_title: str = Field(..., min_length=1, max_length=200)
    title: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=1, max_length=100000)
    has_spoilers: StrictBool
    rating: float | None = Field(None, ge=0, le=10)

    @field_validator("text")
    @classmethod
    def valid_text(cls, value):
        return validate_words(value, 250, 1500)


class ReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(None, min_length=1, max_length=200)
    text: str | None = Field(None, min_length=1, max_length=100000)
    has_spoilers: StrictBool | None = None
    rating: float | None = Field(None, ge=0, le=10)

    @field_validator("text", "title", "has_spoilers")
    @classmethod
    def not_null(cls, value, info):
        if value is None:
            raise ValueError("Поле не может быть null")
        return validate_words(value, 250, 1500) if info.field_name == "text" else value


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    anime_source: str
    anime_external_id: str
    anime_title: str
    text: str
    title: str
    has_spoilers: bool
    author_name: str
    anime_rating: float | None
    date: datetime
    likes_count: int = 0
    dislikes_count: int = 0
    liked_by_me: bool = False
    disliked_by_me: bool = False
