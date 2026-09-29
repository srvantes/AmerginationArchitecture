from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


AnimeSource = Literal["shikimori", "animego", "kodik"]


class ReviewCreate(BaseModel):
    anime_source: AnimeSource = "shikimori"
    anime_external_id: str = Field(..., min_length=1, max_length=100)
    anime_title: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=1, max_length=6000)
    rating: float | None = Field(None, ge=0, le=10)


class ReviewUpdate(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=6000)
    rating: float | None = Field(None, ge=0, le=10)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    anime_source: str
    anime_external_id: str
    anime_title: str
    text: str
    anime_rating: float | None
    date: datetime
