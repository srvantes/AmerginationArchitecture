from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AchievementCode = Literal["email_verified", "first_anime", "ten_anime", "eleven_likes", "first_review"]


class AchievementOut(BaseModel):
    code: AchievementCode
    title: str
    description: str
    target: int
    awarded_at: datetime | None
    showcase_slot: int | None


class MyAchievement(AchievementOut):
    progress: int


class ShowcaseSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codes: list[AchievementCode] = Field(max_length=4)

    @field_validator("codes")
    @classmethod
    def unique_codes(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Одно достижение нельзя выбрать дважды")
        return value
