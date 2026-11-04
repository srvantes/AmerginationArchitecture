import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from backend.database.sсhemas.catalog import AnimeCard
from backend.services import catalog_service as service
from backend.services.posters import poster_url


def card(identifier, url=None):
    return AnimeCard(source="shikimori", external_id=str(identifier), title="Anime", poster_url=url)


def payload(ids, missing=()):
    return {"data": {"animes": [{"id": identifier, "poster": None if identifier in missing else
        {"mainUrl": f"https://shikimori.io/uploads/poster/animes/{identifier}/main.webp"}}
        for identifier in ids]}}


class PosterTests(unittest.IsolatedAsyncioTestCase):
    def test_placeholder_and_unsafe_urls_are_not_posters(self):
        for value in [None, "", "javascript:alert(1)", "https://user:secret@example.com/a.jpg",
                      "/assets/globals/missing_original.jpg", "//shikimori.one/assets/globals/missing_preview.jpg"]:
            self.assertIsNone(poster_url(value, service.SHIKI), value)
        self.assertEqual(poster_url("/poster.jpg", service.SHIKI), service.SHIKI + "/poster.jpg")
        self.assertEqual(poster_url("https://cdn.example/poster.jpg", service.SHIKI), "https://cdn.example/poster.jpg")

    async def test_batching_deduplication_and_current_urls_for_cached_legacy_cards(self):
        cards = [card(i) for i in range(1, 54)] + [card(1)]

        async def fetch(path, **kwargs):
            ids = kwargs["json_body"]["variables"]["ids"].split(",")
            self.assertEqual(path, "graphql")
            self.assertLessEqual(len(ids), 50)
            result = payload(ids)
            kwargs["validator"](result)
            return result

        with patch.object(service, "cached_shiki", side_effect=fetch) as upstream:
            await service.apply_posters(cards)
        self.assertEqual(upstream.await_count, 2)
        self.assertTrue(all("/uploads/poster/animes/" in str(item.poster_url) for item in cards))
        self.assertEqual(cards[0].poster_url, cards[-1].poster_url)

    async def test_null_poster_and_known_missing_image_are_replaced_with_no_image(self):
        cards = [card(1, service.SHIKI + "/assets/globals/missing_original.jpg"),
                 card(2, service.SHIKI + "/old.jpg")]
        with patch.object(service, "cached_shiki", AsyncMock(return_value=payload(["1", "2"], missing=["2"]))):
            await service.apply_posters(cards)
        self.assertIn("/uploads/", str(cards[0].poster_url))
        self.assertIsNone(cards[1].poster_url)

    async def test_poster_failure_preserves_working_images_and_does_not_hide_titles(self):
        cards = [card(1, "https://images.example/working.jpg"),
                 card(2, service.SHIKI + "/assets/globals/missing_original.jpg")]
        with patch.object(service, "cached_shiki", AsyncMock(side_effect=HTTPException(504, "timeout"))):
            await service.apply_posters(cards)
        self.assertEqual(str(cards[0].poster_url), "https://images.example/working.jpg")
        self.assertIsNone(cards[1].poster_url)

    async def test_non_shikimori_cards_do_not_contact_shikimori(self):
        cards = [AnimeCard(source="animego", external_id="1", title="Anime")]
        with patch.object(service, "cached_shiki", AsyncMock()) as upstream:
            await service.apply_posters(cards)
        upstream.assert_not_awaited()

    async def test_graphql_cache_is_shared_and_partial_or_mismatched_responses_are_rejected(self):
        storage = {}

        async def write(key, ttl, data):
            storage[key] = data

        with patch.object(service, "get_cached_json", side_effect=lambda key: storage.get(key)), \
             patch.object(service, "set_cached_json", side_effect=write), \
             patch.object(service, "shiki_request", AsyncMock(return_value=payload(["1"]))) as upstream:
            await service.apply_posters([card(1)])
            await service.apply_posters([card(1)])
        self.assertEqual(upstream.await_count, 1)
        self.assertIn("post:", next(iter(storage)))
        for result in [{"errors": [{"message": "offline"}], **payload(["1"])}, payload(["999"]),
                       {"data": {"animes": [{"id": "1", "poster": True}]}},
                       {"data": {"animes": [None]}}]:
            with self.subTest(result=result), self.assertRaises(HTTPException):
                service._poster_mapping(result, ["1"])
