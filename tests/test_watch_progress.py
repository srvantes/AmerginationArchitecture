import unittest
from unittest.mock import AsyncMock, patch

from backend.services.watch_progress import known_episode_total


class ProgressMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_total_comes_from_server_cache(self):
        with patch("backend.services.watch_progress.get_cached_json", AsyncMock(return_value={"details": {"episodes_total": 24}})) as cache:
            self.assertEqual(await known_episode_total("shikimori", "20"), 24)
            cache.assert_awaited_once_with("catalog:page:v1:shikimori:20")

    async def test_missing_or_malformed_metadata_has_no_invented_limit(self):
        for value in (None, 0, -1, True, "12", {"details": None}):
            with patch("backend.services.watch_progress.get_cached_json", AsyncMock(return_value=value)):
                self.assertIsNone(await known_episode_total("animego", "500"))

    async def test_metadata_survives_partial_catalog_page_failure(self):
        with patch("backend.services.watch_progress.get_cached_json", AsyncMock(side_effect=[None, 12])) as cache:
            self.assertEqual(await known_episode_total("shikimori", "20"), 12)
            self.assertEqual(cache.await_args_list[1].args, ("catalog:progress-total:v1:shikimori:20",))
