import html
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from backend.services import animego_service as service


def response(content):
    result = Mock()
    result.json.return_value = {"data": {"content": content}}
    return result


def button(number, video_id):
    return f'<div data-episode-number="{number}" data-episode="{video_id}"></div>'


def initial(total=3):
    pages = html.escape(json.dumps([{"page": 0}, {"page": 1}, {"page": 2}]), quote=True)
    return (f"<div data-anime-player-episodes-pages-value='{pages}' "
            f'data-anime-player-episodes-total-value="{total}">'
            + button(1, 1618) + '</div>')


class EpisodePaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_pages_sorted_deduplicated_and_cached_with_video_ids(self):
        def upstream(url, **kwargs):
            page = (kwargs.get("params") or {}).get("page", 0)
            return response({0: initial(), 1: button(101, 1718),
                             2: button(101, 1718) + button(500, 2117)}[page])
        with patch.object(service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(service, "set_cached_json", AsyncMock()) as cache, \
             patch.object(service.requests, "get", side_effect=upstream) as request:
            episodes = await service.get_episodes_from_page("naruto-103")
        self.assertEqual([item["seria"] for item in episodes], [1, 101, 500])
        self.assertEqual(episodes[-1]["video_id"], "2117")
        self.assertEqual(request.call_count, 3)
        cache.assert_awaited_once_with("animego:episodes_page:v4:103", 43200, episodes)

    async def test_incomplete_page_is_not_cached(self):
        with patch.object(service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(service, "set_cached_json", AsyncMock()) as cache, \
             patch.object(service.requests, "get", return_value=response(initial())):
            with self.assertRaises(HTTPException) as caught:
                await service.get_episodes_from_page("103")
        self.assertEqual(caught.exception.status_code, 502)
        cache.assert_not_awaited()

    async def test_late_episode_primes_parser_from_persistent_index(self):
        episodes = [{"seria": 1, "video_id": "1618"}, {"seria": 500, "video_id": "2117"}]
        def voices(anime_id, episode):
            self.assertTrue(service._parser._get_player_url_for_episode(anime_id, episode).endswith("/videos/2117"))
            return {"voices": [], "total_episodes": None}
        with patch.object(service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(service, "set_cached_json", AsyncMock()), \
             patch.object(service, "get_episodes_from_page", AsyncMock(return_value=episodes)), \
             patch.object(service._parser, "_player_url_cache", {}), \
             patch.object(service._parser, "get_voices", side_effect=voices):
            result = await service.get_voices_cached("103", 500)
        self.assertEqual(result["total_episodes"], 500)

    async def test_cached_voices_restore_episode_url_after_restart(self):
        episodes = [{"seria": 500, "video_id": "2117"}]
        cached = {"voices": [], "total_episodes": 500}
        with patch.object(service, "get_cached_json", AsyncMock(return_value=cached)), \
             patch.object(service, "get_episodes_from_page", AsyncMock(return_value=episodes)), \
             patch.object(service._parser, "_player_url_cache", {}), \
             patch.object(service._parser, "get_voices") as parser:
            self.assertEqual(await service.get_voices_cached("103", 500), cached)
            self.assertTrue(service._parser._get_player_url_for_episode("103", 500).endswith("/videos/2117"))
        parser.assert_not_called()

    async def test_missing_episode_returns_404_without_calling_parser(self):
        with patch.object(service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(service, "get_episodes_from_page", AsyncMock(return_value=[{"seria": 1}])), \
             patch.object(service._parser, "get_voices") as parser:
            with self.assertRaises(HTTPException) as caught:
                await service.get_voices_cached("103", 501)
        self.assertEqual(caught.exception.status_code, 404)
        parser.assert_not_called()

    async def test_schedule_metadata_and_late_playable_episodes_are_merged(self):
        schedule = [{"seria": 1, "title": "Homecoming", "air_date": "2007-02-15", "is_released": False}]
        player = [{"seria": 1, "title": "Серия 1", "is_released": True},
                  {"seria": 500, "title": "Серия 500", "is_released": True}]
        with patch.object(service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(service, "set_cached_json", AsyncMock()), \
             patch.object(service, "_run_sync", AsyncMock(return_value=schedule)), \
             patch.object(service, "get_episodes_from_page", AsyncMock(return_value=player)):
            result = await service.get_episodes_info("103")
        self.assertEqual([item["seria"] for item in result], [1, 500])
        self.assertEqual(result[0]["title"], "Homecoming")
        self.assertEqual(result[0]["air_date"], "2007-02-15")
        self.assertTrue(result[0]["is_released"])
