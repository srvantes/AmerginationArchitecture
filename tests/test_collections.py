import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.services import catalog_service as service
from main import app


def anime(identifier, score="8.0", **fields):
    return {"id": identifier, "name": f"Anime {identifier}", "russian": f"Аниме {identifier}",
            "url": f"/animes/{identifier}", "image": {"original": f"/{identifier}.jpg"},
            "kind": "tv", "status": "released", "score": score, **fields}


class CollectionServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = patch.object(service, "remember_titles", AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(service, "apply_posters", AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_home_only_loads_two_initial_lists_and_nine_ordered_descriptors(self):
        with patch.object(service, "cached_shiki", AsyncMock(return_value=[anime(1)])) as source:
            result = await service.home_catalog(12)
        self.assertEqual(source.await_count, 2)
        self.assertEqual([item.slug for item in result.collections], [
            "shounen", "shoujo", "seinen", "josei", "fantasy", "comedy", "drama", "isekai", "romance"])
        self.assertEqual([item.title for item in result.collections], [
            "Сёнен", "Сёдзё", "Сэйнэн", "Дзёсэй", "Фэнтези", "Комедии", "Драмы", "Исекай", "Романтика"])
        self.assertTrue(all(item.order == "ranked" for item in result.collections))
        self.assertEqual(len(result.ongoing), 1)
        self.assertEqual(len(result.popular), 1)
        self.assertEqual(result.warnings, [])
        self.assertTrue(all(call.args[0] == "animes" and call.args[1]["limit"] == 50
                            for call in source.await_args_list))

    async def test_each_theme_uses_verified_v2_ids_and_includes_ongoing_and_specials(self):
        identifiers = {"shounen": "27", "shoujo": "25", "seinen": "42", "josei": "43",
                       "fantasy": "10", "comedy": "4", "drama": "8", "isekai": "130", "romance": "22"}
        with patch.object(service, "cached_shiki", AsyncMock(return_value=[anime(1)])) as source:
            for slug, identifier in identifiers.items():
                with self.subTest(slug=slug):
                    result = await service.collection_catalog(slug, 12)
                    call = source.await_args
                    self.assertEqual(call.args[0], "animes")
                    self.assertEqual(call.args[1], {"status": "released,ongoing",
                        "kind": "tv,movie,ova,ona,special,tv_special", "order": "ranked", "limit": 50,
                        "genre_v2": identifier})
                    self.assertEqual(call.kwargs["ttl"], 21600)
                    self.assertEqual(result.slug, slug)
                    self.assertEqual(len(result.items), 1)

    async def test_home_preserves_collection_menu_when_both_initial_shelves_fail(self):
        with patch.object(service, "cached_shiki", AsyncMock(side_effect=HTTPException(504, "timeout"))):
            result = await service.home_catalog(12)
        self.assertEqual(result.ongoing, [])
        self.assertEqual(result.popular, [])
        self.assertEqual(len(result.warnings), 2)
        self.assertEqual(len(result.collections), 9)
        self.assertEqual(result.collections[7].slug, "isekai")

    async def test_ranked_top_fifty_are_deduplicated_and_stably_sorted_before_limit(self):
        raw = [anime(1, "8.2"), anime(2, "9.1"), anime(1, "9.9"),
               anime(3, "9.1"), anime(4, "0"), anime(5, None)]
        with patch.object(service, "cached_shiki", AsyncMock(return_value=raw)) as source:
            result = await service.collection_catalog("fantasy", 4)
        self.assertEqual([item.external_id for item in result.items], ["2", "3", "1", "4"])
        self.assertEqual([item.score for item in result.items], [9.1, 9.1, 8.2, 0])
        self.assertEqual(source.await_count, 1)  # One list request; no per-title detail lookup.
        self.assertEqual(result.order, "ranked")

    async def test_ongoing_keeps_source_popularity_order_and_short_ttl(self):
        with patch.object(service, "cached_shiki", AsyncMock(return_value=[anime(1, "6"), anime(2, "9")])) as source:
            result = await service.collection_catalog("ongoing")
        self.assertEqual([item.external_id for item in result.items], ["1", "2"])
        self.assertEqual(source.await_args.args[1], {"status": "ongoing", "kind": "tv,ona",
                                                    "order": "popularity", "limit": 50})
        self.assertEqual(source.await_args.kwargs["ttl"], 1800)

    async def test_small_and_full_limits_share_one_raw_top_fifty_cache(self):
        cache = {}

        async def read(key):
            return cache.get(key)

        async def write(key, ttl, data):
            cache[key] = data

        with patch.object(service, "get_cached_json", side_effect=read), \
             patch.object(service, "set_cached_json", side_effect=write) as writes, \
             patch.object(service, "shiki_request", AsyncMock(return_value=[anime(i) for i in range(1, 51)])) as upstream:
            small = await service.collection_catalog("romance", 12)
            full = await service.collection_catalog("romance", 50)
        self.assertEqual((len(small.items), len(full.items)), (12, 50))
        self.assertEqual(upstream.await_count, 1)
        self.assertEqual(writes.await_args.args[1], 21600)
        self.assertEqual(len(cache), 1)

    async def test_concurrent_limits_share_load_even_when_one_client_cancels(self):
        started, complete = asyncio.Event(), asyncio.Event()

        async def fetch(*args):
            started.set()
            await complete.wait()
            return [anime(i) for i in range(1, 51)]

        with patch.object(service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(service, "set_cached_json", AsyncMock()), \
             patch.object(service, "shiki_request", side_effect=fetch) as upstream:
            first = asyncio.create_task(service.collection_catalog("shounen", 12))
            await started.wait()
            second = asyncio.create_task(service.collection_catalog("shounen", 50))
            await asyncio.sleep(0)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            complete.set()
            result = await second
        self.assertEqual(len(result.items), 50)
        self.assertEqual(upstream.await_count, 1)

    async def test_invalid_and_failed_source_responses_are_not_cached_as_empty_success(self):
        for payload in ({"error": "no"}, [anime(1), {"id": 2}], [{"id": True}]):
            with self.subTest(payload=payload), \
                 patch.object(service, "get_cached_json", AsyncMock(return_value=None)), \
                 patch.object(service, "set_cached_json", AsyncMock()) as cache, \
                 patch.object(service, "shiki_request", AsyncMock(return_value=payload)), \
                 self.assertRaises(HTTPException) as caught:
                await service.collection_catalog("drama")
            self.assertEqual(caught.exception.status_code, 502)
            cache.assert_not_awaited()
        with patch.object(service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(service, "set_cached_json", AsyncMock()) as cache, \
             patch.object(service, "shiki_request", AsyncMock(side_effect=HTTPException(504, "timeout"))), \
             self.assertRaises(HTTPException) as caught:
            await service.collection_catalog("drama")
        self.assertEqual(caught.exception.status_code, 504)
        cache.assert_not_awaited()

    async def test_broken_cached_list_is_rebuilt_and_provider_n_plus_one_is_trimmed(self):
        with patch.object(service, "get_cached_json", AsyncMock(return_value={"broken": True})), \
             patch.object(service, "set_cached_json", AsyncMock()) as cache, \
             patch.object(service, "shiki_request", AsyncMock(return_value=[anime(i) for i in range(1, 52)])) as upstream:
            result = await service.collection_catalog("comedy", 50)
        self.assertEqual(len(result.items), 50)
        self.assertNotIn("51", [item.external_id for item in result.items])
        self.assertEqual(upstream.await_count, 1)
        cache.assert_awaited_once()

    async def test_unknown_slug_does_not_contact_any_provider(self):
        with patch.object(service, "cached_shiki", AsyncMock()) as source, self.assertRaises(HTTPException) as caught:
            await service.collection_catalog("not-a-collection")
        self.assertEqual(caught.exception.status_code, 404)
        source.assert_not_awaited()

    async def test_public_budget_spaces_burst_and_rejects_full_minute_without_long_wait(self):
        budget = service._ShikiRequestBudget()
        clock = [100.0]

        async def sleep(seconds):
            clock[0] += seconds

        with patch.object(service, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(service.asyncio, "sleep", side_effect=sleep):
            await asyncio.gather(*(budget.admit() for _ in range(11)))
            starts = list(budget.starts)
            self.assertTrue(all(second - first >= .259 for first, second in zip(starts, starts[1:])))
            self.assertLess(clock[0] - 100, 3)  # All cold shelves, not a minute-long queue.
            budget.starts.extend([clock[0]] * (80 - len(budget.starts)))
            before = clock[0]
            with self.assertRaises(HTTPException) as caught:
                await budget.admit()
            self.assertEqual(caught.exception.status_code, 503)
            self.assertIn("Retry-After", caught.exception.headers)
            self.assertEqual(clock[0], before)


class CollectionRouteTests(unittest.TestCase):
    def test_collection_route_precedes_generic_provider_and_validates_limit(self):
        response = service.CatalogCollection(slug="isekai", title="Исекай", order="ranked",
                                             items=[service.shiki_card(anime(1))])
        with TestClient(app) as client, \
             patch("backend.api.v1.endpoints.anime.collection_catalog", AsyncMock(return_value=response)) as source:
            result = client.get("/api/v1/anime/catalog/collections/isekai?limit=12")
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["items"][0]["external_id"], "1")
            source.assert_awaited_once_with("isekai", 12)
            for limit in (0, 51):
                self.assertEqual(client.get(f"/api/v1/anime/catalog/collections/isekai?limit={limit}").status_code, 422)

    def test_unknown_collection_returns_clear_404_and_frontend_url_loads_index(self):
        with TestClient(app) as client:
            result = client.get("/api/v1/anime/catalog/collections/unknown")
            self.assertEqual(result.status_code, 404)
            self.assertEqual(result.json()["detail"], "Подборка не найдена")
            page = client.get("/collections/shounen")
            self.assertEqual(page.status_code, 200)
            self.assertIn("text/html", page.headers["content-type"])
