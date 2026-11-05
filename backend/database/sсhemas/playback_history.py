from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, TypeAdapter, field_validator


PlaybackSource = Literal["shikimori", "animego"]
PlaybackPlayer = Literal["aniboom", "kodik", "cvh", "sibnet"]
PlaybackAnimeId = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$", max_length=20)]


class PlaybackHistoryWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    anime_title: str = Field(min_length=1, max_length=200)
    poster_url: str | None = Field(None, max_length=2048)
    anime_slug: str | None = Field(None, max_length=300, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    episode: int = Field(ge=1, le=100000, strict=True)
    player: PlaybackPlayer
    translation_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$", max_length=20)
    translation_source: Literal["animego", "kodik"] = "animego"
    translation_name: str = Field(min_length=1, max_length=200)

    @field_validator("anime_title", "translation_name")
    @classmethod
    def reject_control_characters(cls, value):
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Название не должно содержать управляющие символы")
        return value

    @field_validator("poster_url")
    @classmethod
    def validate_poster_url(cls, value):
        if value is None:
            return None
        if any(ord(character) < 33 or ord(character) == 127 for character in value):
            raise ValueError("Некорректная ссылка на постер")
        url = TypeAdapter(AnyHttpUrl).validate_python(value)
        if url.username is not None or url.password is not None:
            raise ValueError("Ссылка на постер не должна содержать пароль или логин")
        return str(url)


class PlaybackHistoryOut(PlaybackHistoryWrite):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True, extra="forbid")

    id: UUID
    anime_source: PlaybackSource
    anime_external_id: PlaybackAnimeId
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def timestamp_in_utc(cls, value):
        # SQLite drops tzinfo in tests; PostgreSQL keeps the timestamptz offset.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
