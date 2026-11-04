import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from redis.exceptions import ConnectionError

from backend.core import cache


class RegistryBatchCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_mget_decodes_one_batch_and_ignores_only_damaged_entries(self):
        redis = AsyncMock()
        redis.mget.return_value = ['{"title":"Нана"}', None, 'not json']
        with patch.object(cache, "redis_client", redis):
            self.assertEqual(await cache.get_cached_json_many(["one", "two", "bad"]), {"one": {"title": "Нана"}})
        redis.mget.assert_awaited_once_with(["one", "two", "bad"])

    async def test_writes_use_one_pipeline_with_expiry_and_empty_batches_do_nothing(self):
        pipeline = MagicMock()
        pipeline.execute = AsyncMock()
        pipeline.__aenter__ = AsyncMock(return_value=pipeline)
        pipeline.__aexit__ = AsyncMock(return_value=None)
        redis = MagicMock()
        redis.pipeline.return_value = pipeline
        with patch.object(cache, "redis_client", redis):
            await cache.set_cached_json_many({}, 60)
            redis.pipeline.assert_not_called()
            await cache.set_cached_json_many({"one": {"title": "Нана"}, "two": [2]}, 60)
        redis.pipeline.assert_called_once_with(transaction=False)
        self.assertEqual(pipeline.setex.call_count, 2)
        pipeline.execute.assert_awaited_once()
        self.assertTrue(all(call.args[1] == 60 for call in pipeline.setex.call_args_list))

    async def test_redis_outage_is_a_cache_miss(self):
        redis = AsyncMock()
        redis.mget.side_effect = ConnectionError("offline")
        with patch.object(cache, "redis_client", redis):
            self.assertEqual(await cache.get_cached_json_many(["one"]), {})
