from redis.asyncio import Redis
from typing import AsyncGenerator
from fastapi import Depends

from .config import settings

async def get_redis_client() -> AsyncGenerator[Redis, None]:
    redis_client = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        db=settings.REDIS_DB,
        decode_responses=True
    )
    try:
        yield redis_client
    finally:
        await redis_client.close()

redis_client = Redis()