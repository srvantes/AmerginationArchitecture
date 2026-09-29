from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
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
    socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT_SECONDS,
    socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
    retry=Retry(NoBackoff(), 0),
)


async def close_redis():
    await redis_client.aclose()

