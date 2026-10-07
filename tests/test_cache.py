import unittest
from unittest.mock import AsyncMock, patch

from redis.exceptions import RedisError

from backend.core.cache import get_cached_json, set_cached_json


class CacheTests(unittest.IsolatedAsyncioTestCase):
    @patch("backend.core.cache.redis_client")
    async def test_cached_json_is_decoded(self, redis_client):
        redis_client.get = AsyncMock(return_value='{"title": "Naruto"}')
        self.assertEqual(await get_cached_json("anime:20"), {"title": "Naruto"})

    @patch("backend.core.cache.redis_client")
    async def test_read_failure_becomes_cache_miss(self, redis_client):
        redis_client.get = AsyncMock(side_effect=RedisError("offline"))
        self.assertIsNone(await get_cached_json("anime:20"))

    @patch("backend.core.cache.redis_client")
    async def test_value_is_encoded_and_stored_with_ttl(self, redis_client):
        redis_client.setex = AsyncMock()
        await set_cached_json("anime:20", 60, {"title": "Naruto"})
        redis_client.setex.assert_awaited_once_with(
            "anime:20", 60, '{"title": "Naruto"}'
        )
