import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.database.sсhemas.catalog import AnimeCard, AnimeDetails
from backend.services import catalog_service as service
from main import app


SHIKI = {"id": 1735, "name": "Naruto: Shippuuden", "russian": "Наруто: Ураганные хроники",
         "url": "/animes/z1735-naruto-shippuuden", "image": {"original": "/poster.jpg"},
         "aired_on": "2007-02-15", "kind": "tv", "status": "released", "score": "8.29",
         "genres": [{"name": "Action", "russian": "Экшен"}], "description": "Real description", "episodes": 500}
ANIMEGO = {"id": "103", "title": "Наруто: Ураганные хроники", "original_title": "Naruto: Shippuuden",
           "year": 2007, "type": "Сериал", "slug": "naruto-uragannye-hroniki",
           "link": "https://animego.org/anime/naruto-uragannye-hroniki-103"}


class LiveCatalogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, mock in [("remember_titles", AsyncMock()), ("get_title", AsyncMock(return_value=None))]:
            patcher = patch.object(service, name, mock)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(service, "apply_posters", AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_matching_requires_exact_title_year_and_kind(self):
        reference = service.shiki_card(SHIKI)
        card = AnimeCard(source="animego", external_id="103", title=reference.title, year=2007, kind="Сериал")
        wrong_year = card.model_copy(update={"external_id": "104", "year": 2017})
        wrong_kind = card.model_copy(update={"external_id": "105", "kind": "Фильм"})
        partial = card.model_copy(update={"external_id": "106", "title": "Наруто"})
        unknown_year = card.model_copy(update={"external_id": "107", "year": None})
        self.assertEqual(service.matching_cards(reference, [wrong_year, wrong_kind, partial, unknown_year, card]), [card])

    async def test_ambiguous_mapping_does_not_choose_first_player(self):
        with patch.object(service, "search_animego", AsyncMock(return_value=[ANIMEGO, {**ANIMEGO, "id": "999"}])), \
             patch.object(service, "set_cached_json", AsyncMock()) as cache:
            result = await service.animego_match(AnimeDetails(**service.shiki_card(SHIKI).model_dump()))
        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.animego_id)
        cache.assert_not_awaited()

    async def test_mapping_keeps_provider_ids_separate(self):
        with patch.object(service, "search_animego", AsyncMock(return_value=[ANIMEGO])), \
             patch.object(service, "set_cached_json", AsyncMock()):
            result = await service.animego_match(AnimeDetails(**service.shiki_card(SHIKI).model_dump()))
        self.assertEqual((result.shikimori_id, result.animego_id, result.method), ("1735", "103", "title_year_kind"))

    async def test_page_contains_real_genres_description_and_only_anime_relations(self):
        async def upstream(path, *args, **kwargs):
            return SHIKI if path == "animes/1735" else [{"anime": SHIKI, "relation_russian": "Продолжение"}, {"anime": None, "manga": {"id": 1}}]
        with patch.object(service, "cached_shiki", side_effect=upstream), \
             patch.object(service, "animego_match", AsyncMock(return_value=service.PlaybackMatch(status="not_found"))):
            page = await service.shiki_page("1735")
        self.assertEqual(page.details.description, "Real description")
        self.assertEqual(page.details.genres, ["Экшен"])
        self.assertEqual(len(page.related), 1)
        self.assertEqual(page.related[0].relation, "Продолжение")

    async def test_home_keeps_successful_shelf_when_other_fails(self):
        async def upstream(path, params, **kwargs):
            if params["status"] == "ongoing":
                raise HTTPException(504, "timeout")
            return [SHIKI]
        with patch.object(service, "cached_shiki", side_effect=upstream):
            result = await service.home_catalog(6)
        self.assertEqual(result.ongoing, [])
        self.assertEqual(len(result.popular), 1)
        self.assertEqual(len(result.warnings), 1)

    async def test_known_animego_id_is_not_rematched_when_enriching_details(self):
        async def upstream(path, *args, **kwargs):
            return SHIKI if path == "animes/1735" else []
        with patch.object(service, "cached_shiki", side_effect=upstream), \
             patch.object(service, "animego_match", AsyncMock()) as matcher:
            page = await service.shiki_page("1735", known_animego_id="103")
        self.assertEqual(page.playback.animego_id, "103")
        self.assertEqual(page.playback.method, "same_source")
        matcher.assert_not_awaited()

    async def test_deferred_card_never_waits_for_animego_or_caches_pending_match(self):
        async def upstream(path, *args, **kwargs):
            return SHIKI if path == "animes/1735" else []
        with patch.object(service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(service, "cached_shiki", side_effect=upstream), \
             patch.object(service, "animego_match", AsyncMock()) as matcher, \
             patch.object(service, "set_cached_json", AsyncMock()) as cache:
            page = await service.catalog_page("shikimori", "1735", defer_playback=True)
        self.assertEqual(page.playback.status, "pending")
        self.assertEqual(page.details.title, "Наруто: Ураганные хроники")
        matcher.assert_not_awaited()
        self.assertFalse(any(call.args[0].startswith("catalog:page:") for call in cache.await_args_list))

    async def test_catalog_cache_avoids_refetching_and_preserves_mapping(self):
        page = service.CatalogPage(details=AnimeDetails(**service.shiki_card(SHIKI).model_dump()),
                                   playback=service.PlaybackMatch(status="matched", animego_id="103", shikimori_id="1735"))
        with patch.object(service, "get_cached_json", AsyncMock(return_value=page.model_dump(mode="json"))), \
             patch.object(service, "set_cached_json", AsyncMock()) as identity_cache, \
             patch.object(service, "shiki_page", AsyncMock()) as upstream:
            result = await service.catalog_page("shikimori", "1735")
        self.assertEqual(result, page)
        upstream.assert_not_awaited()
        identity_cache.assert_awaited_once_with("catalog:playback-shikimori:v1:103", 21600,
                                               {"shikimori_id": "1735"})

    async def test_unverified_or_mismatched_identity_is_not_remembered(self):
        details = AnimeDetails(**service.shiki_card(SHIKI).model_dump())
        with patch.object(service, "set_cached_json", AsyncMock()) as cache:
            for playback in [service.PlaybackMatch(status="ambiguous", shikimori_id="1735"),
                             service.PlaybackMatch(status="matched", animego_id="103", shikimori_id="20")]:
                page = service.CatalogPage(details=details, playback=playback)
                await service.remember_playback_identity(page)
        cache.assert_not_awaited()

    async def test_animego_slug_cannot_be_an_external_url(self):
        with patch.object(service, "get_cached_json", AsyncMock(return_value=None)), \
             self.assertRaises(HTTPException) as caught:
            await service.animego_page("103", "https://localhost/private")
        self.assertEqual(caught.exception.status_code, 422)

    def test_route_rejects_unknown_provider_and_invalid_ids(self):
        with TestClient(app) as client:
            for path in ["/api/v1/anime/catalog/other/123", "/api/v1/anime/catalog/shikimori/abc", "/api/v1/anime/catalog/home?limit=31"]:
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 422)
