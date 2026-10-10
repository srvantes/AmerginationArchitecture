import unittest
from unittest.mock import AsyncMock, Mock, patch

from anime_parsers_ru import errors
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.services import animego_service, shikimori_client
from backend.services.catalog_adapters import anime_details, player_info, stream_info
from main import app


SHIKI_CARD = {
    "shikimori_id": "20", "title": "Наруто", "original_title": "Naruto",
    "link": "https://shikimori.io/animes/z20-naruto",
    "poster": "/system/animes/original/20.jpg", "genres": ["Экшен"],
    "year": "2002", "type": "TV Сериал", "status": "вышло", "studio": None,
}
ANIMEGO_CARD = {
    "id": "103", "slug": "naruto", "title": "Наруто", "original_title": None,
    "link": "https://animego.org/anime/naruto-103",
    "image": "//animego.org/poster.jpg", "rating": "8,4", "year": 2002, "type": "TV",
}
ANIMEGO_VOICES = {
    "voices": [{"translation_id": "17", "label": "Studio", "player": "CVH",
                "embed": "https://example.com/cdn-iframe/123/1", "cvh_id": "123"}],
    "total_episodes": None,
}
KODIK_INFO = {
    "series_count": 24,
    "translations": [{"id": "610", "name": "Studio", "type": "voice", "series_range": [1, 12]}],
}


class CatalogContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def call_with(self, function, payload, path, **params):
        with patch(f"backend.api.v1.endpoints.anime.{function}", AsyncMock(return_value=payload)):
            return self.client.get("/api/v1/anime/" + path, params=params)

    def test_search_sources_share_card_contract(self):
        shiki = self.call_with("search_anime_cached", [SHIKI_CARD], "search", q="Naruto")
        animego = self.call_with("search_animego", [ANIMEGO_CARD], "animego/search", q="Naruto")
        self.assertEqual(shiki.status_code, 200, shiki.text)
        self.assertEqual(animego.status_code, 200, animego.text)
        first, second = shiki.json()[0], animego.json()[0]
        self.assertEqual(set(first), set(second))
        self.assertEqual(first["external_id"], "20")
        self.assertEqual(second["external_id"], "103")
        self.assertEqual(second["slug"], "naruto")
        self.assertEqual(first["year"], 2002)
        self.assertEqual(second["score"], 8.4)
        self.assertEqual(first["poster_url"], "https://shikimori.io/system/animes/original/20.jpg")
        self.assertEqual(second["poster_url"], "https://animego.org/poster.jpg")

    def test_details_preserve_known_metadata_and_unknown_counts(self):
        details = {
            "title": "Наруто", "original_title": "Naruto", "picture": None,
            "episodes": "12 / ?", "description": "Story", "rating": "PG-13",
            "score": "8.1", "themes": None, "genres": None,
            "episode_duration": "24 мин.", "licensed_in_ru": "Наруто",
        }
        response = self.call_with(
            "get_anime_details_cached", details, "details",
            shikimori_link="https://shikimori.io/animes/z20-naruto",
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["external_id"], "20")
        self.assertEqual(result["episodes_aired"], 12)
        self.assertIsNone(result["episodes_total"])
        self.assertEqual(result["episodes_text"], "12 / ?")
        self.assertEqual(result["age_rating"], "PG-13")
        self.assertEqual(result["score"], 8.1)
        self.assertEqual(result["genres"], [])
        for raw, total, aired in [("12", 12, None), ("6 / 12", 12, 6), (None, None, None)]:
            normalized = anime_details({**details, "episodes": raw}, "https://shikimori.io/animes/20-naruto")
            self.assertEqual((normalized.episodes_total, normalized.episodes_aired), (total, aired))

    def test_episodes_and_release_state(self):
        response = self.call_with("get_episodes_info", [
            {"seria": 1, "title": "Episode", "air_date": "9 октября 2026", "is_released": False},
        ], "animego/episodes", anime_id="103")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["episodes"][0]["number"], 1)
        self.assertFalse(response.json()["episodes"][0]["is_released"])

    def test_translations_share_contract_and_keep_provider_identity(self):
        voices = self.call_with("get_voices_cached", ANIMEGO_VOICES, "animego/voices", anime_id="103")
        kodik = self.call_with("get_player_info_cached", KODIK_INFO, "kodik/info", shikimori_id="20")
        self.assertEqual(voices.status_code, 200, voices.text)
        self.assertEqual(kodik.status_code, 200, kodik.text)
        first, second = voices.json(), kodik.json()
        self.assertEqual(set(first), set(second))
        self.assertEqual(first["translations"][0]["player"], "cvh")
        self.assertIsNone(first["episodes_total"])
        self.assertEqual(second["id_source"], "shikimori")
        self.assertEqual(second["translations"][0]["episodes_end"], 12)
        self.assertEqual(set(first["translations"][0]), set(second["translations"][0]))
        self.assertEqual(player_info({"translations": [], "series_count": 0}, "kodik", "1").episodes_total, 0)

    def test_streams_normalize_hls_dash_and_mp4(self):
        for payload, formats in [
            ({"url": "//example.com/manifest.mpd", "kind": "MPD", "player": "aniboom"}, ["dash"]),
            ({"url": "https://example.com/video.m3u8", "kind": "HLS", "player": "aniboom"}, ["hls"]),
            ({"hls": "https://example.com/video.m3u8", "dash": "https://example.com/video.mpd",
              "mp4": ["https://example.com/video.mp4"], "player": "cvh"}, ["hls", "dash", "mp4"]),
        ]:
            response = self.call_with(
                "get_stream_url", payload, "animego/stream",
                anime_id="103", episode=1, translation_id="17", player=payload["player"],
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual([item["format"] for item in response.json()["streams"]], formats)
            self.assertEqual(response.json()["translation_id"], "17")
        response = self.call_with("get_stream_url_cached", {
            "stream_url": "https://example.com/video.m3u8", "quality": 720, "type": "hls",
        }, "kodik/stream", shikimori_id="20", episode=0, translation_id="610")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["streams"][0]["quality"], 720)
        self.assertEqual(response.json()["episode"], 0)

    def test_malformed_upstream_payload_returns_502(self):
        with self.assertLogs("backend.services.catalog_adapters", level="ERROR"):
            response = self.call_with("search_anime_cached", [{"title": "Missing ID"}], "search", q="Naruto")
        self.assertEqual(response.status_code, 502)
        with self.assertLogs("backend.services.catalog_adapters", level="ERROR"):
            for data in [{"player": "cvh"}, {"player": "aniboom", "url": "bad", "kind": "HLS"}]:
                with self.assertRaises(HTTPException) as error:
                    stream_info(data, "animego", "103", 1, "17")
                self.assertEqual(error.exception.status_code, 502)

    def test_only_404_triggers_episode_fallback(self):
        for code in [404, 502, 504]:
            with patch("backend.api.v1.endpoints.anime.get_episodes_info", AsyncMock(
                side_effect=HTTPException(status_code=code, detail="failure"),
            )), patch("backend.api.v1.endpoints.anime.get_episodes_from_page", AsyncMock(return_value=[])) as fallback:
                response = self.client.get("/api/v1/anime/animego/episodes", params={"anime_id": "103"})
                self.assertEqual(response.status_code, 200 if code == 404 else code)
                self.assertEqual(fallback.await_count, 1 if code == 404 else 0)

    def test_empty_schedule_uses_player_episode_list(self):
        with patch("backend.api.v1.endpoints.anime.get_episodes_info", AsyncMock(return_value=[])), \
             patch("backend.api.v1.endpoints.anime.get_episodes_from_page", AsyncMock(return_value=[
                 {"seria": 1, "title": "Episode", "is_released": True},
             ])) as fallback:
            response = self.client.get("/api/v1/anime/animego/episodes", params={"anime_id": "naruto-103"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["episodes"][0]["number"], 1)
        fallback.assert_awaited_once_with("103")

    def test_embedded_player_selects_translation_and_provider_together(self):
        voices = {"voices": [
            {"translation_id": "9", "label": "Studio", "player": "Kodik", "embed": "https://example.com/kodik"},
            {"translation_id": "9", "label": "Studio", "player": "Sibnet", "embed": "https://example.com/sibnet"},
        ]}
        with patch.object(animego_service, "get_voices_cached", AsyncMock(return_value=voices)) as upstream:
            response = self.client.get("/api/v1/anime/animego/player", params={
                "anime_id": "naruto-103", "episode": 2, "translation_id": "9", "player": "sibnet",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["embed_url"], "https://example.com/sibnet")
        self.assertEqual(response.json()["external_id"], "103")
        upstream.assert_awaited_once_with("103", 2)

    def test_missing_embedded_translation_returns_404(self):
        with patch.object(animego_service, "get_voices_cached", AsyncMock(return_value={"voices": []})):
            response = self.client.get("/api/v1/anime/animego/player", params={
                "anime_id": "103", "translation_id": "9", "player": "kodik",
            })
        self.assertEqual(response.status_code, 404)

    def test_invalid_embed_url_returns_502(self):
        with patch.object(animego_service, "get_voices_cached", AsyncMock(return_value={"voices": [
            {"translation_id": "9", "label": "Studio", "player": "Kodik", "embed": "javascript:alert(1)"},
        ]})), self.assertLogs("backend.services.catalog_adapters", level="ERROR"):
            response = self.client.get("/api/v1/anime/animego/player", params={
                "anime_id": "103", "translation_id": "9", "player": "kodik",
            })
        self.assertEqual(response.status_code, 502)

    def test_watch_page_is_available(self):
        response = self.client.get("/watch")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_openapi_documents_all_catalog_responses(self):
        schema = self.client.get("/openapi.json").json()
        for path in ["/search", "/details", "/animego/search", "/animego/episodes",
                     "/animego/voices", "/animego/stream", "/kodik/info", "/kodik/stream"]:
            response = schema["paths"]["/api/v1/anime" + path]["get"]["responses"]["200"]
            self.assertIn("schema", response["content"]["application/json"])

    def test_invalid_player_is_rejected(self):
        response = self.client.get("/api/v1/anime/animego/stream", params={
            "anime_id": "103", "episode": 1, "translation_id": "17", "player": "unknown",
        })
        self.assertEqual(response.status_code, 422)

    def test_kodik_quality_query_is_parsed_as_number(self):
        for quality in [360, 480, 720, 1080]:
            with patch("backend.api.v1.endpoints.anime.get_stream_url_cached", AsyncMock(return_value={
                "stream_url": "https://example.com/video.m3u8", "quality": quality, "type": "hls",
            })) as upstream:
                response = self.client.get("/api/v1/anime/kodik/stream", params={
                    "shikimori_id": "20", "episode": 1, "translation_id": "610", "quality": quality,
                })
            self.assertEqual(response.status_code, 200, response.text)
            upstream.assert_awaited_once_with("20", 1, "610", quality)
        response = self.client.get("/api/v1/anime/kodik/stream", params={
            "shikimori_id": "20", "episode": 1, "translation_id": "610", "quality": 600,
        })
        self.assertEqual(response.status_code, 422)


class ProviderBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_filters_unrelated_titles_and_ranks_exact_match_first(self):
        cards = [
            {"id": "1", "title": "Боруто: Фильм Наруто"},
            {"id": "2", "title": "Наруто: Ураганные хроники"},
            {"id": "3", "title": "Исчезновение Юки Нагато"},
            {"id": "4", "title": "Наруто"},
            {"id": "5", "title": "Дневник Наруми"},
        ]
        with patch.object(animego_service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(animego_service, "set_cached_json", AsyncMock()) as cache, \
             patch.object(animego_service, "_run_sync", AsyncMock(return_value=cards)):
            result = await animego_service.search_animego(" НАРУТО ")
        self.assertEqual([item["id"] for item in result], ["4", "2", "1"])
        cache.assert_awaited_once_with("animego:search:v2:наруто", 86400, result)

    def test_search_matches_original_title_and_slug_without_fuzzy_matches(self):
        cards = [
            {"id": "1", "title": "Наруто", "original_title": "Naruto"},
            {"id": "2", "title": "Наруто: Ураганные хроники", "slug": "naruto-shippuuden"},
            {"id": "3", "title": "Кайдзю", "original_title": "Narumi"},
        ]
        result = animego_service._relevant_search_results(cards, ["naruto"])
        self.assertEqual([item["id"] for item in result], ["1", "2"])

    def test_search_normalizes_yo_punctuation_and_matches_all_words(self):
        words = animego_service._search_words("  ТЁМНОЕ — царство! ")
        cards = [{"title": "Тёмное царство"}, {"title": "Тёмное море"},
                 {"title": "Царство", "original_title": "Темное"}]
        self.assertEqual(words, ["темное", "царство"])
        self.assertEqual(animego_service._relevant_search_results(cards, words), cards[:1])

    def test_search_allows_partial_words_and_returns_empty_when_no_match(self):
        cards = [{"title": "Наруто: Ураганные хроники"}, {"title": "Другое аниме"}]
        self.assertEqual(animego_service._relevant_search_results(cards, ["нар", "ураг"]), cards[:1])
        self.assertEqual(animego_service._relevant_search_results(cards, ["несуществующее"]), [])

    async def test_search_reuses_normalized_cache_without_fetching_provider(self):
        cards = [{"title": "Тёмное царство"}]
        with patch.object(animego_service, "get_cached_json", AsyncMock(return_value=cards)) as cache, \
             patch.object(animego_service, "_run_sync", AsyncMock()) as run:
            self.assertEqual(await animego_service.search_animego(" ТЁМНОЕ   царство "), cards)
        cache.assert_awaited_once_with("animego:search:v2:темное царство")
        run.assert_not_awaited()

    async def test_search_rejects_blank_or_punctuation_queries(self):
        for query in ["  ", "---", "а!"]:
            with self.subTest(query=query), self.assertRaises(HTTPException) as caught:
                await animego_service.search_animego(query)
            self.assertEqual(caught.exception.status_code, 422)

    async def test_slug_is_converted_before_calling_parser(self):
        with patch.object(animego_service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(animego_service, "set_cached_json", AsyncMock()), \
             patch.object(animego_service, "_run_sync", AsyncMock(return_value=[])) as run:
            await animego_service.get_episodes_info("naruto-uragannye-khroniki-2-svyazi-3127")
        run.assert_awaited_once_with(animego_service._parser.get_episodes_info, "3127")

    async def test_library_http_404_is_exposed_for_fallback(self):
        for status in [404, 403, 503]:
            with patch.object(animego_service, "get_cached_json", AsyncMock(return_value=None)), \
                 patch.object(animego_service, "_run_sync", AsyncMock(side_effect=errors.ServiceError(
                     f"Ошибка при поиске на AnimeGO. Ожидался код 200, получен: {status}",
                 ))):
                with self.assertRaises(HTTPException) as error:
                    await animego_service.get_episodes_info("3127")
                self.assertEqual(error.exception.status_code, 404 if status == 404 else 502)

    async def test_fallback_uses_numeric_player_endpoint(self):
        response = Mock()
        response.json.return_value = {"data": {"content":
            '<button data-episode-number="1"></button><button data-episode-number="2"></button>'}}
        with patch.object(animego_service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(animego_service, "set_cached_json", AsyncMock()), \
             patch.object(animego_service.requests, "get", return_value=response) as request:
            episodes = await animego_service.get_episodes_from_page("naruto-3127")
        self.assertEqual([item["seria"] for item in episodes], [1, 2])
        self.assertTrue(request.call_args.args[0].endswith("/player/3127"))

    async def test_selected_player_is_respected(self):
        voices = {"voices": [
            {"translation_id": "17", "label": "First", "player": "AniBoom"},
            {"translation_id": "17", "label": "Second", "player": "CVH", "cvh_id": "123"},
        ]}
        with patch.object(animego_service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(animego_service, "get_voices_cached", AsyncMock(return_value=voices)), \
             patch.object(animego_service, "set_cached_json", AsyncMock()), \
             patch.object(animego_service, "_run_sync", AsyncMock(return_value={"HLS": "https://example.com/video.m3u8"})) as run:
            result = await animego_service.get_stream_url("103", 1, "17", "cvh")
        self.assertEqual(result["player"], "cvh")
        self.assertEqual(result["translation"], "Second")
        self.assertEqual(run.call_args.kwargs["cvh_id"], "123")

    async def test_unknown_episode_count_does_not_invent_episodes(self):
        with patch.object(animego_service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(animego_service, "_run_sync", AsyncMock(return_value=[])), \
             patch.object(animego_service, "get_voices_cached", AsyncMock(return_value={"total_episodes": None})), \
             patch.object(animego_service, "set_cached_json", AsyncMock()):
            self.assertEqual(await animego_service.get_episodes_from_page("naruto-103"), [])

    async def test_empty_search_and_missing_episodes_are_distinguished(self):
        with patch.object(animego_service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(animego_service, "_run_sync", AsyncMock(side_effect=errors.NoResults("missing"))):
            self.assertEqual(await animego_service.search_animego("missing"), [])
            with self.assertRaises(HTTPException) as error:
                await animego_service.get_episodes_info("103")
            self.assertEqual(error.exception.status_code, 404)

    async def test_cached_and_fresh_search_responses_have_same_shape(self):
        parser = AsyncMock()
        parser.search.return_value = [SHIKI_CARD]
        with patch.object(shikimori_client, "get_cached_json", AsyncMock(side_effect=[None, [SHIKI_CARD]])), \
             patch.object(shikimori_client, "set_cached_json", AsyncMock()), \
             patch.object(shikimori_client, "ShikimoriParserAsync", Mock(return_value=parser)):
            fresh = await shikimori_client.search_anime_cached("Naruto")
            cached = await shikimori_client.search_anime_cached("Naruto")
        self.assertEqual(fresh, cached)
        parser.search.assert_awaited_once()
        parser.close_async_session.assert_awaited_once()
