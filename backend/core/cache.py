import json
import logging
from typing import Any

from redis.exceptions import RedisError

from .redis import redis_client


logger = logging.getLogger(__name__)


async def get_cached_json(key: str) -> Any | None:
    """Read JSON from Redis without making Redis a hard dependency."""
    try:
        cached = await redis_client.get(key)
    except RedisError as exc:
        logger.warning("Redis read failed for key %s: %s", key, exc)
        return None

    if cached is None:
        return None

    try:
        return json.loads(cached)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.warning("Invalid JSON in Redis for key %s: %s", key, exc)
        return None


async def set_cached_json(key: str, ttl: int, value: Any) -> None:
    """Write JSON to Redis; the upstream request remains usable if Redis is down."""
    try:
        payload = json.dumps(value, ensure_ascii=False)
        await redis_client.setex(key, ttl, payload)
    except (RedisError, TypeError, ValueError) as exc:
        logger.warning("Redis write failed for key %s: %s", key, exc)
