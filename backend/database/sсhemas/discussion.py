import re
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

AnimeSource = Literal["shikimori", "animego", "kodik"]
AnimeId = Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]


def word_count(value):
    # Spaces separate words; punctuation by itself does not count as a word.
    return sum(any(char.isalnum() for char in word) for word in re.findall(r"\S+", value))


def validate_words(value, minimum, maximum):
    value = value.strip()
    count = word_count(value)
    if not minimum <= count <= maximum:
        raise ValueError(f"Текст должен содержать от {minimum} до {maximum} слов")
    return value


class CommentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=20000)
    has_spoilers: StrictBool = False

    @field_validator("text")
    @classmethod
    def valid_text(cls, value):
        return validate_words(value, 1, 250)


class CommentCreate(CommentUpdate):
    anime_source: AnimeSource
    anime_external_id: AnimeId
