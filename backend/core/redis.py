from redis.asyncio import Redis
from typing import AsyncGenerator
from fastapi import Depends

from .config import settings

#   print("🚨🚨🚨 ЗАГРУЖАЮ REDIS С ПАРОЛЕМ: None 🚨🚨🚨")
redis_client = Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    password=settings.REDIS_PASSWORD or None,
    db=settings.REDIS_DB,
    decode_responses=True,
    max_connections=settings.REDIS_MAX_CONNECTIONS,
)


async def close_redis():
    await redis_client.close()

