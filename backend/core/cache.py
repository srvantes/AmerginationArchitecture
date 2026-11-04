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


async def get_cached_json_many(keys: list[str]) -> dict[str, Any]:
    if not keys:
        return {}
    try:
        values = await redis_client.mget(keys)
    except RedisError as exc:
        logger.warning("Redis batch read failed (%s)", type(exc).__name__)
        return {}
    result = {}
    for key, raw in zip(keys, values):
        if raw is not None:
            try:
                result[key] = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                logger.warning("Invalid JSON in Redis for key %s", key)
    return result


async def set_cached_json_many(values: dict[str, Any], ttl: int) -> None:
    if not values:
        return
    try:
        payloads = {key: json.dumps(value, ensure_ascii=False) for key, value in values.items()}
        async with redis_client.pipeline(transaction=False) as pipeline:
            for key, payload in payloads.items():
                pipeline.setex(key, ttl, payload)
            await pipeline.execute()
    except (RedisError, TypeError, ValueError) as exc:
        logger.warning("Redis batch write failed (%s)", type(exc).__name__)
