from pydantic import BaseModel, EmailStr, Field, field_validator


class ResetRequest(BaseModel):
    email: EmailStr = Field(max_length=100)

    @field_validator("email")
    @classmethod
    def normalize(cls, value):
        return value.lower()


class ResetCode(ResetRequest):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$", strict=True)


class ResetFinish(BaseModel):
    reset_token: str = Field(min_length=40, max_length=100, strict=True)
    new_password: str = Field(min_length=8, max_length=128, strict=True)
