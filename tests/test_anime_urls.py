import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.database.sсhemas.catalog import AnimeCard
from backend.services import catalog_service
from backend.services.anime_urls import anime_path, parse_anime_key
from main import app


class AnimeUrlTests(unittest.TestCase):
    def test_readable_name_uses_original_title_and_stable_id(self):
        card = AnimeCard(source="shikimori", external_id="877", title="Нана", original_title="Nana")
        self.assertEqual(card.public_path, "/anime/nana-877")
        self.assertEqual(card.model_dump()["public_path"], "/anime/nana-877")
        self.assertEqual(AnimeCard.model_validate(card.model_dump()).public_path, card.public_path)
        self.assertEqual(anime_path("shikimori", "12531", "Дети на холме", "Sakamichi no Apollon"),
                         "/anime/sakamichi-no-apollon-12531")

    def test_provider_id_collisions_stay_separate(self):
        self.assertEqual(anime_path("animego", "877", "Нана", slug="nana"), "/anime/nana-a877")
        self.assertEqual(parse_anime_key("nana-877")["source"], "shikimori")
        self.assertEqual(parse_anime_key("nana-a877"), {"source": "animego", "external_id": "877", "slug": "nana"})

    def test_titles_are_safe_and_transliterated_without_query_strings(self):
        self.assertEqual(anime_path("shikimori", "20", "Наруто"), "/anime/naruto-20")
        self.assertEqual(anime_path("shikimori", "1", "Été / ?#<script>"), "/anime/ete-script-1")
        self.assertEqual(anime_path("shikimori", "1", "日本語"), "/anime/anime-1")
        self.assertLess(len(anime_path("shikimori", "1", "x" * 1000)), 180)
        self.assertEqual(anime_path("animego", "308", "Нана", slug="https://evil.example/"), "/anime/nana-a308")
        for source, identifier in [("kodik", "1"), ("other", "1"), ("shikimori", "0"),
                                   ("shikimori", "01"), ("shikimori", "1/2")]:
            self.assertIsNone(anime_path(source, identifier, "Title"))
        for key in ["nana", "nana-0", "nana-01", "nana-1?source=other", "nana-1/", "../nana-1"]:
            self.assertIsNone(parse_anime_key(key))

    def test_clean_routes_support_direct_open_and_refresh_without_upstream_requests(self):
        with TestClient(app) as client, patch("main.legacy_anime_path", AsyncMock()) as resolve:
            for path in ["/anime/nana-877", "/anime/nana-a308", "/anime/wrong-title-877"]:
                response = client.get(path)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn('id="anime-page"', response.text)
            self.assertEqual(client.get("/anime/nana-0").status_code, 404)
            resolve.assert_not_awaited()

    def test_old_links_redirect_and_remove_provider_and_slug_query(self):
        with TestClient(app) as client, patch("main.legacy_anime_path", AsyncMock(return_value="/anime/nana-877")) as resolve:
            response = client.get("/anime/shikimori/877", follow_redirects=False)
            self.assertEqual((response.status_code, response.headers["location"]), (301, "/anime/nana-877"))
            resolve.assert_awaited_once_with("shikimori", "877", None)
        with TestClient(app) as client, patch("main.legacy_anime_path", AsyncMock(return_value="/anime/nana-a308")) as resolve:
            for path in ["/anime/animego/308?slug=nana", "/anime/308?slug=nana"]:
                response = client.get(path, follow_redirects=False)
                self.assertEqual((response.status_code, response.headers["location"]), (301, "/anime/nana-a308"))
                self.assertNotIn("?", response.headers["location"])
            self.assertEqual(resolve.await_args.args, ("animego", "308", "nana"))

    def test_bad_legacy_source_and_id_never_load_upstream_metadata(self):
        with TestClient(app) as client, patch("main.legacy_anime_path", AsyncMock()) as resolve:
            for path in ["/anime/other/877", "/anime/shikimori/not-an-id", "/anime/shikimori/0"]:
                self.assertEqual(client.get(path).status_code, 422)
            resolve.assert_not_awaited()


class LegacyAnimeUrlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, mock in [("remember_titles", AsyncMock()), ("get_title", AsyncMock(return_value=None))]:
            patcher = patch.object(catalog_service, name, mock)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_saved_list_spelling_uses_the_verified_upstream_slug(self):
        card = AnimeCard(source="animego", external_id="1939", title="Аполлон: Дети на холме",
                         slug="apollon-deti-na-holme", page_url="https://animego.me/anime/apollon-deti-na-holme-1939")
        with patch.object(catalog_service, "get_cached_json", AsyncMock(return_value=card.model_dump(mode="json"))), \
             patch.object(catalog_service, "_run_sync", AsyncMock(return_value={})) as load, \
             patch.object(catalog_service, "cached_shiki", AsyncMock(side_effect=HTTPException(503, "offline"))):
            page = await catalog_service.animego_page("1939", "deti-na-holme")
            self.assertTrue(load.await_args.args[1].endswith("/anime/apollon-deti-na-holme-1939"))
            self.assertEqual(page.details.public_path, "/anime/apollon-deti-na-holme-a1939")

    async def test_bad_slug_is_rejected_even_when_a_verified_card_is_cached(self):
        with patch.object(catalog_service, "get_cached_json", AsyncMock()) as cache, \
             patch.object(catalog_service, "_run_sync", AsyncMock()) as load:
            with self.assertRaises(HTTPException) as error:
                await catalog_service.animego_page("308", "https://evil.example/")
            self.assertEqual(error.exception.status_code, 422)
            cache.assert_not_awaited()
            load.assert_not_awaited()

    async def test_shikimori_redirect_uses_metadata_without_player_search(self):
        data = {"id": 877, "name": "Nana", "russian": "Нана", "url": "/animes/877-nana"}
        with patch.object(catalog_service, "cached_shiki", AsyncMock(return_value=data)) as get, \
             patch.object(catalog_service, "search_animego", AsyncMock()) as search:
            self.assertEqual(await catalog_service.legacy_anime_path("shikimori", "877"), "/anime/nana-877")
            get.assert_awaited_once_with("animes/877")
            search.assert_not_awaited()

    async def test_animego_slug_and_cached_card_do_not_need_upstream_requests(self):
        card = AnimeCard(source="animego", external_id="308", title="Нана", slug="nana")
        cache = AsyncMock(side_effect=[None, card.model_dump(mode="json")])
        with patch.object(catalog_service, "get_cached_json", cache):
            self.assertEqual(await catalog_service.legacy_anime_path("animego", "308", "nana"), "/anime/nana-a308")
            cache.assert_not_awaited()
            self.assertEqual(await catalog_service.legacy_anime_path("animego", "308"), "/anime/nana-a308")
