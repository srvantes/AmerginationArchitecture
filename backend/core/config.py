from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str = 'localhost'
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = 'postgres'

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}:{self.POSTGRES_port}/{self.POSTGRES_DB}"


'''    class Config:
        env_file = '.env'''



@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()