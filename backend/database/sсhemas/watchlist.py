from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .anime import AnimeSource


WatchStatus = Literal["planned", "watching", "completed", "on_hold", "dropped"]


class WatchlistCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    anime_source: AnimeSource = "shikimori"
    anime_external_id: str = Field(min_length=1, max_length=100)
    anime_title: str = Field(min_length=1, max_length=200)
    status: WatchStatus = "planned"
    episodes_watched: int = Field(0, ge=0, le=2147483647, strict=True)


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
    status: WatchStatus
    episodes_watched: int
    created_at: datetime
    updated_at: datetime
