from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator, AnyHttpUrl, TypeAdapter

from .anime import AnimeSource


WatchStatus = Literal["planned", "watching", "completed", "on_hold", "dropped"]


class WatchlistCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    anime_source: AnimeSource = "shikimori"
    anime_external_id: str = Field(min_length=1, max_length=100)
    anime_title: str = Field(min_length=1, max_length=200)
    poster_url: str | None = Field(None, max_length=2048)
    anime_slug: str | None = Field(None, max_length=300, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    status: WatchStatus = "planned"
    episodes_watched: int = Field(0, ge=0, le=2147483647, strict=True)

    @field_validator("poster_url")
    @classmethod
    def validate_poster_url(cls, value):
        return str(TypeAdapter(AnyHttpUrl).validate_python(value)) if value is not None else None


class WatchlistUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    anime_title: str | None = Field(None, min_length=1, max_length=200)
    status: WatchStatus | None = None
    episodes_watched: int | None = Field(None, ge=0, le=2147483647, strict=True)

    @model_validator(mode="before")
    @classmethod
    def reject_null_fields(cls, data):
        if isinstance(data, dict) and any(value is None for value in data.values()):
            raise ValueError("Watchlist fields cannot be null")
        return data


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    anime_source: AnimeSource
    anime_external_id: str
    anime_title: str
    poster_url: str | None = None
    anime_slug: str | None = None
    status: WatchStatus
    episodes_watched: int
    episodes_total: int | None = None
    created_at: datetime
    updated_at: datetime


class WatchlistSummary(BaseModel):
    completed: int
    episodes_watched: int
    reviews_written: int
    total: int
    watching: list[WatchlistOut]
