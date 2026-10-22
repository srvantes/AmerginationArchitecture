from typing import Literal, Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):

    POSTGRES_USER: Optional[str] = None
    POSTGRES_PASSWORD: Optional[str] = None
    POSTGRES_HOST: str = 'localhost'
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: Optional[str] = None

    SECRET_KEY: str = Field(min_length=32)
    ALGORITHM: Literal["HS256"] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    SQL_ECHO: bool = False
    EXTERNAL_SERVICE_TIMEOUT_SECONDS: float = Field(default=20.0, gt=0, le=120)
    EXTERNAL_CONNECT_TIMEOUT_SECONDS: float = Field(default=3.0, gt=0, le=30)
    EXTERNAL_READ_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0, le=60)
    EXTERNAL_SERVICE_ATTEMPTS: int = Field(default=2, ge=1, le=3)
    EXTERNAL_RETRY_MAX_DELAY_SECONDS: float = Field(default=2.0, ge=0, le=5)

    REGISTRATION_LIMIT_PER_HOUR: int = Field(default=3, ge=1, le=10000)
    LOGIN_LIMIT_PER_5_MINUTES: int = Field(default=30, ge=1, le=10000)
    LOGIN_ACCOUNT_LIMIT_PER_5_MINUTES: int = Field(default=10, ge=1, le=10000)
    COMMENT_LIMIT_PER_HOUR: int = Field(default=20, ge=1, le=10000)
    COMMENT_COOLDOWN_SECONDS: int = Field(default=15, ge=1, le=3600)
    LIKE_LIMIT_PER_MINUTE: int = Field(default=30, ge=1, le=10000)
    DISCUSSION_EDIT_LIMIT_PER_MINUTE: int = Field(default=30, ge=1, le=10000)
    REVIEW_LIMIT_PER_HOUR: int = Field(default=5, ge=1, le=10000)
    EMAIL_SEND_LIMIT_PER_HOUR: int = Field(default=5, ge=1, le=10000)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = Field(default=465, ge=1, le=65535)
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: SecretStr | None = None
    SMTP_FROM_EMAIL: str | None = None
    SMTP_TIMEOUT_SECONDS: float = Field(default=10, gt=0, le=30)

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0
    REDIS_MAX_CONNECTIONS: int = 100
    REDIS_CONNECT_TIMEOUT_SECONDS: float = 1.0
    REDIS_SOCKET_TIMEOUT_SECONDS: float = 1.0

    KODIK_TOKEN: str | None = None

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


    class Config:
        env_file = '.env'



@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
