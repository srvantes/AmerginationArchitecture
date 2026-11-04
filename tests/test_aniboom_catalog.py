import asyncio
import html
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from backend.services.player_catalogs import aniboom


EMBED = "https://aniboom.one/embed/AnimeId?episode=1&translation=9&episodes=1"
ENDPOINT = "https://aniboom.one/embed/AnimeId/episodes?_expiration=9999999999&_hash=" + "a" * 32 + "&domain=animego.me&translation=9"
REAL_CLIENT = httpx.AsyncClient


def embed_html(endpoint=ENDPOINT, **changes):
    picker = {"endpoint": endpoint, "animeId": "AnimeId", "translation": 9, "translationTitle": "2x2"} | changes
    return '<video data-parameters="' + html.escape(json.dumps({"episodePicker": picker}), quote=True) + '"></video>'


class AniboomCatalogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Cache helpers return None when Redis is unavailable. Never touch Redis here.
        read = patch.object(aniboom, "get_cached_json", AsyncMock(return_value=None))
        write = patch.object(aniboom, "set_cached_json", AsyncMock(return_value=None))
        self.read_cache, self.write_cache = read.start(), write.start()
        self.addCleanup(read.stop)
        self.addCleanup(write.stop)
        interval = patch.object(aniboom, "DETAILS_START_INTERVAL_SECONDS", 0)
        interval.start()
        self.addCleanup(interval.stop)

    def mock_client(self, handler):
        return patch.object(aniboom.httpx, "AsyncClient", side_effect=lambda **kwargs: REAL_CLIENT(
            transport=httpx.MockTransport(handler), **kwargs))

    async def test_exact_translation_membership_batching_and_concurrency(self):
        calls, active, maximum = [], 0, 0

        async def handler(request):
            nonlocal active, maximum
            calls.append(request)
            if request.method == "GET":
                self.assertEqual(request.headers["referer"], "https://animego.me/")
                return httpx.Response(200, text=embed_html())
            self.assertEqual(request.headers["origin"], aniboom.ORIGIN)
            self.assertEqual(request.headers["referer"], EMBED)
            data = json.loads(request.content)
            if data["action"] == "catalog":
                return httpx.Response(200, json={"numbers": list(range(100, 0, -1))})
            self.assertLessEqual(len(data["numbers"]), 30)
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            return httpx.Response(200, json={"items": [{"episode": number, "available": number in {1, 4, 100},
                                                       "alternatives": [{"translation": 40, "title": "Other"}]}
                                                      for number in data["numbers"]]})

        with self.mock_client(handler):
            result = await aniboom.get_episode_numbers(EMBED, "9")
        self.assertEqual(result, [1, 4, 100])
        self.assertEqual(len(calls), 6)  # Embed + catalog + four batches, not 100 per-episode reads.
        self.assertLessEqual(maximum, 3)

    async def test_empty_catalog_is_valid(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, text=embed_html()) if request.method == "GET" else httpx.Response(200, json={"numbers": []})

        with self.mock_client(handler):
            self.assertEqual(await aniboom.get_episode_numbers(EMBED, "9"), [])
        self.assertEqual(len(calls), 2)

    async def test_animego_voice_uses_its_bound_aniboom_translation_id(self):
        # Real provider mapping: AnimeGo's СВ-Дубль=66, Aniboom's СВ-Дубль=15.
        embed = EMBED.replace("translation=9", "translation=15")
        endpoint = ENDPOINT.replace("translation=9", "translation=15")
        calls = []

        def handler(request):
            calls.append(request)
            if request.method == "GET":
                return httpx.Response(200, text=embed_html(endpoint, translation=15,
                                                         translationTitle="СВ-Дубль"))
            self.assertEqual(request.url.params["translation"], "15")
            payload = json.loads(request.content)
            return httpx.Response(200, json={"numbers": [1, 4]} if payload["action"] == "catalog"
                                  else {"items": [{"episode": 1, "available": True},
                                                  {"episode": 4, "available": False}]})

        with self.mock_client(handler):
            self.assertEqual(await aniboom.get_episode_numbers(embed, "66"), [1])
        self.assertEqual(len(calls), 3)
        self.assertIn(":AnimeId:15:", self.write_cache.await_args.args[0])

    async def test_missing_duplicate_or_invalid_embed_translation_never_reaches_network(self):
        invalid = [EMBED.replace("&translation=9", ""), EMBED + "&translation=15",
                   EMBED.replace("translation=9", "translation="),
                   EMBED.replace("translation=9", "translation=-1"),
                   EMBED.replace("translation=9", "translation=abc")]

        def handler(request):
            self.fail("An ambiguous translation reached the network")

        with self.mock_client(handler):
            for embed in invalid:
                with self.subTest(embed=embed), self.assertRaises(HTTPException):
                    await aniboom.get_episode_numbers(embed, "66")

    async def test_picker_must_match_embed_even_when_animego_id_matches_picker(self):
        embed = EMBED.replace("translation=9", "translation=15")
        endpoint = ENDPOINT.replace("translation=9", "translation=66")
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, text=embed_html(endpoint, translation=66))

        with self.mock_client(handler), self.assertRaises(HTTPException):
            await aniboom.get_episode_numbers(embed, "66")
        self.assertEqual(len(calls), 1)
        self.write_cache.assert_not_awaited()

    async def test_detail_request_starts_are_paced_within_one_operation(self):
        starts = []

        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, text=embed_html())
            data = json.loads(request.content)
            if data["action"] == "catalog":
                return httpx.Response(200, json={"numbers": list(range(1, 91))})
            starts.append(asyncio.get_running_loop().time())
            return httpx.Response(200, json={"items": [{"episode": number, "available": True}
                                                      for number in data["numbers"]]})

        with self.mock_client(handler), patch.object(aniboom, "DETAILS_START_INTERVAL_SECONDS", 0.01):
            self.assertEqual(len(await aniboom.get_episode_numbers(EMBED, "9")), 90)
        self.assertEqual(len(starts), 3)
        self.assertTrue(all(later - earlier >= 0.009 for earlier, later in zip(starts, starts[1:])))

    async def test_untrusted_input_urls_never_reach_network(self):
        def handler(request):
            self.fail("Untrusted URL reached transport")

        for url in ["http://aniboom.one/embed/AnimeId", "https://127.0.0.1/embed/AnimeId",
                    "https://aniboom.one.evil/embed/AnimeId", "https://user:pass@aniboom.one/embed/AnimeId",
                    "https://aniboom.one:444/embed/AnimeId", "https://aniboom.one/embed/%2e%2e/private",
                    "https://aniboom.one/embed/AnimeId#fragment", "https://aniboom.one/other/AnimeId"]:
            with self.subTest(url=url), self.mock_client(handler):
                with self.assertRaises(HTTPException) as caught:
                    await aniboom.get_episode_numbers(url, "9")
                self.assertEqual(caught.exception.status_code, 502)

    async def test_endpoint_cannot_change_host_path_or_translation(self):
        endpoints = [ENDPOINT.replace("aniboom.one", "127.0.0.1"),
                     ENDPOINT.replace("/embed/AnimeId/episodes", "/embed/Other/episodes"),
                     ENDPOINT.replace("translation=9", "translation=40"),
                     ENDPOINT + "&translation=9", ENDPOINT.replace("domain=animego.me", "domain=127.0.0.1"),
                     "https://user:password@aniboom.one/embed/AnimeId/episodes", ENDPOINT.replace("https:", "http:")]
        for endpoint in endpoints:
            calls = []

            def handler(request):
                calls.append(request)
                return httpx.Response(200, text=embed_html(endpoint))

            with self.subTest(endpoint=endpoint), self.mock_client(handler):
                with self.assertRaises(HTTPException):
                    await aniboom.get_episode_numbers(EMBED, "9")
            self.assertEqual(len(calls), 1)

    async def test_picker_identity_and_schema_are_required(self):
        for body in [embed_html(translation=40), embed_html(translation=True), embed_html(animeId="Other"),
                     '<video data-parameters="invalid"></video>', "<html>Missing player</html>"]:
            with self.subTest(body=body), self.mock_client(lambda request: httpx.Response(200, text=body)):
                with self.assertRaises(HTTPException):
                    await aniboom.get_episode_numbers(EMBED, "9")

    async def test_redirects_are_rejected_at_embed_and_signed_endpoint(self):
        for redirect_embed in [True, False]:
            calls = []

            def handler(request):
                calls.append(request)
                if redirect_embed or request.method == "POST":
                    return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
                return httpx.Response(200, text=embed_html())

            with self.subTest(redirect_embed=redirect_embed), self.mock_client(handler):
                with self.assertRaises(HTTPException) as caught:
                    await aniboom.get_episode_numbers(EMBED, "9")
                self.assertEqual(caught.exception.status_code, 502)
            self.assertEqual(len(calls), 1 if redirect_embed else 2)

    async def test_invalid_catalog_and_incomplete_details_do_not_return_partial_lists(self):
        for catalog, details in [([True], []), ([0], []), (["1"], []),
                                 ([1, 4], [{"episode": 1, "available": True}]),
                                 ([1], [{"episode": 1, "available": "true"}]),
                                 ([1], [{"episode": 2, "available": True}]),
                                 ([1, 4], [{"episode": 1, "available": True}, {"episode": 1, "available": True}])]:
            def handler(request):
                if request.method == "GET":
                    return httpx.Response(200, text=embed_html())
                data = json.loads(request.content)
                return httpx.Response(200, json={"numbers": catalog} if data["action"] == "catalog" else {"items": details})

            with self.subTest(catalog=catalog, details=details), self.mock_client(handler):
                with self.assertRaises(HTTPException):
                    await aniboom.get_episode_numbers(EMBED, "9")
        self.write_cache.assert_not_awaited()

    async def test_validated_batches_survive_other_batch_failure_and_skip_on_retry(self):
        storage, requested = {}, []
        fail = True

        async def read(key):
            return storage.get(key)

        async def write(key, ttl, value):
            self.assertEqual(ttl, 600)
            self.assertNotIn("_hash", key)
            self.assertNotIn("_expiration", key)
            self.assertNotIn("https", key)
            storage[key] = value

        self.read_cache.side_effect = read
        self.write_cache.side_effect = write

        async def handler(request):
            if request.method == "GET":
                return httpx.Response(200, text=embed_html())
            data = json.loads(request.content)
            if data["action"] == "catalog":
                return httpx.Response(200, json={"numbers": list(range(1, 32))})
            requested.append(data["numbers"])
            if data["numbers"] == [31] and fail:
                # Allow the valid sibling to finish and persist before this failure.
                await asyncio.sleep(0)
                return httpx.Response(400)
            return httpx.Response(200, json={"items": [{"episode": number, "available": number % 2 == 0}
                                                      for number in data["numbers"]]})

        with self.mock_client(handler):
            with self.assertRaises(HTTPException):
                await aniboom.get_episode_numbers(EMBED, "9")
            self.assertEqual(len(storage), 1)
            requested.clear()
            fail = False
            self.assertEqual(await aniboom.get_episode_numbers(EMBED, "9"), list(range(2, 31, 2)))
        self.assertEqual(requested, [[31]])
        self.assertEqual(len(storage), 2)

    async def test_corrupt_or_mismatched_cache_is_ignored(self):
        for cached in [{"checked": [1], "available": [True]},
                       {"checked": [1], "available": [4]},
                       {"checked": [1, 2], "available": [1]},
                       {"checked": [1], "available": [1, 1]}]:
            self.read_cache.return_value = cached
            calls = []

            def handler(request):
                if request.method == "GET":
                    return httpx.Response(200, text=embed_html())
                data = json.loads(request.content)
                calls.append(data["action"])
                return httpx.Response(200, json={"numbers": [1]} if data["action"] == "catalog"
                                      else {"items": [{"episode": 1, "available": True}]})

            with self.subTest(cached=cached), self.mock_client(handler):
                self.assertEqual(await aniboom.get_episode_numbers(EMBED, "9"), [1])
            self.assertEqual(calls, ["catalog", "details"])

    async def test_upstream_failures_do_not_expose_signed_urls(self):
        def handler(request):
            return httpx.Response(200, text=embed_html()) if request.method == "GET" else httpx.Response(403)

        with self.mock_client(handler):
            with self.assertRaises(HTTPException) as caught:
                await aniboom.get_episode_numbers(EMBED, "9")
        self.assertEqual(caught.exception.status_code, 502)
        self.assertNotIn("_hash", caught.exception.detail)
        self.assertNotIn("http", caught.exception.detail)

    async def test_one_failed_batch_cancels_other_metadata_reads(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def handler(request):
            if request.method == "GET":
                return httpx.Response(200, text=embed_html())
            data = json.loads(request.content)
            if data["action"] == "catalog":
                return httpx.Response(200, json={"numbers": list(range(1, 91))})
            if data["numbers"][0] == 31:
                await started.wait()
                return httpx.Response(400)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with self.mock_client(handler):
            with self.assertRaises(HTTPException):
                await aniboom.get_episode_numbers(EMBED, "9")
        self.assertTrue(cancelled.is_set())

    async def test_body_limit_and_one_overall_deadline(self):
        with self.mock_client(lambda request: httpx.Response(200, content=b"a" * 65)), patch.object(aniboom, "MAX_BODY_BYTES", 64):
            with self.assertRaises(HTTPException):
                await aniboom.get_episode_numbers(EMBED, "9")

        async def never_finishes(request):
            await asyncio.Event().wait()

        with self.mock_client(never_finishes), patch.object(aniboom.settings, "EXTERNAL_SERVICE_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(HTTPException) as caught:
                await aniboom.get_episode_numbers(EMBED, "9")
        self.assertEqual(caught.exception.status_code, 504)
