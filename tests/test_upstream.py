import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
import requests
from fastapi import HTTPException

from backend.services import upstream, catalog_service, animego_service


class UpstreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_http_failure_retries_then_succeeds(self):
        error = httpx.HTTPStatusError("temporary", request=httpx.Request("GET", "https://example.org"),
                                     response=httpx.Response(503))
        operation = AsyncMock(side_effect=[error, {"ok": True}])
        with patch.object(upstream.asyncio, "sleep", AsyncMock()) as sleep:
            result = await upstream.run_async(operation, "Shikimori")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(operation.await_count, 2)
        sleep.assert_awaited_once()

    async def test_permanent_errors_and_invalid_content_do_not_retry(self):
        for status in (400, 401, 403, 404, 422):
            error = httpx.HTTPStatusError("permanent", request=httpx.Request("GET", "https://example.org"),
                                         response=httpx.Response(status))
            operation = AsyncMock(side_effect=error)
            with self.assertRaises(httpx.HTTPStatusError):
                await upstream.run_async(operation, "Shikimori")
            operation.assert_awaited_once()
        operation = AsyncMock(side_effect=ValueError("invalid JSON"))
        with self.assertRaises(ValueError):
            await upstream.run_async(operation, "Shikimori")
        operation.assert_awaited_once()

    async def test_one_deadline_covers_all_attempts(self):
        async def stalled():
            await asyncio.Event().wait()
        with patch.object(upstream.settings, "EXTERNAL_SERVICE_TIMEOUT_SECONDS", 0.02):
            with self.assertRaises(TimeoutError):
                await upstream.run_async(stalled, "Shikimori")

    async def test_persistent_network_failure_stops_after_two_attempts(self):
        operation = AsyncMock(side_effect=httpx.ConnectTimeout("offline"))
        with patch.object(upstream.asyncio, "sleep", AsyncMock()):
            with self.assertRaises(httpx.ConnectTimeout):
                await upstream.run_async(operation, "Shikimori")
        self.assertEqual(operation.await_count, 2)

    async def test_rate_limit_retry_after_is_respected(self):
        error = httpx.HTTPStatusError("limited", request=httpx.Request("GET", "https://example.org"),
                                     response=httpx.Response(429, headers={"Retry-After": "1"}))
        operation = AsyncMock(side_effect=[error, "ok"])
        with patch.object(upstream.asyncio, "sleep", AsyncMock()) as sleep:
            self.assertEqual(await upstream.run_async(operation, "Shikimori"), "ok")
        sleep.assert_awaited_once_with(1.0)
        error.response.headers["Retry-After"] = "60"
        operation = AsyncMock(side_effect=error)
        with self.assertRaises(httpx.HTTPStatusError):
            await upstream.run_async(operation, "Shikimori")
        operation.assert_awaited_once()

    def test_parser_transport_has_socket_timeouts_and_bounded_retries(self):
        response = Mock(status_code=200)
        with patch.object(upstream.requests, "get", side_effect=[requests.ConnectTimeout(), response]) as get, \
             patch.object(upstream.time, "sleep"):
            self.assertIs(animego_service._parser.__class__.search.__globals__["requests"].get(
                "https://animego.org/search/anime?q=test"), response)
        self.assertEqual(get.call_count, 2)

    def test_sync_http_failure_retries_and_404_does_not(self):
        failed = requests.Response()
        failed.status_code = 503
        failed.headers["Retry-After"] = "0"
        failed._content = b"unavailable"
        failed._content_consumed = True
        success = requests.Response()
        success.status_code = 200
        with patch.object(upstream.requests, "get", side_effect=[failed, success]) as get, \
             patch.object(upstream.time, "sleep"):
            self.assertIs(upstream.get_sync("https://animego.org/player/103"), success)
        self.assertEqual(get.call_count, 2)

        missing = requests.Response()
        missing.status_code = 404
        with patch.object(upstream.requests, "get", return_value=missing) as get:
            self.assertIs(upstream.get_sync("https://animego.org/player/999"), missing)
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs["timeout"], (3.0, 5.0))
        with patch.object(upstream.requests, "get", side_effect=requests.ReadTimeout()) as get, \
             patch.object(upstream.time, "sleep"):
            with self.assertRaises(requests.ReadTimeout):
                upstream.get_sync("https://animego.org/player/103")
        self.assertEqual(get.call_count, 2)

    def test_expired_parser_deadline_stops_new_network_requests(self):
        token = upstream.sync_deadline.set(-1)
        try:
            with patch.object(upstream.requests, "get") as get:
                with self.assertRaises(requests.Timeout):
                    upstream.get_sync("https://animego.org/player/103")
            get.assert_not_called()
        finally:
            upstream.sync_deadline.reset(token)

    async def test_timeout_and_failure_do_not_leak_upstream_details(self):
        for error, code in [(requests.ReadTimeout("private upstream URL"), 504),
                            (RuntimeError("secret-token"), 502)]:
            with patch.object(animego_service, "get_cached_json", AsyncMock(return_value=None)), \
                 patch.object(animego_service, "set_cached_json", AsyncMock()) as cache, \
                 patch.object(animego_service, "_run_sync", AsyncMock(side_effect=error)):
                with self.assertRaises(HTTPException) as caught:
                    await animego_service.search_animego("test")
            self.assertEqual(caught.exception.status_code, code)
            self.assertNotIn("secret", caught.exception.detail)
            self.assertNotIn("private", caught.exception.detail)
            cache.assert_not_awaited()

    async def test_shiki_statuses_are_mapped_and_failed_responses_not_cached(self):
        for status, code in [(404, 404), (403, 502), (503, 502)]:
            transport = httpx.MockTransport(lambda request: httpx.Response(status, request=request))
            real_client = httpx.AsyncClient
            with patch.object(catalog_service.httpx, "AsyncClient", side_effect=lambda **kwargs: real_client(transport=transport, **kwargs)), \
                 patch.object(catalog_service, "get_cached_json", AsyncMock(return_value=None)), \
                 patch.object(catalog_service, "set_cached_json", AsyncMock()) as cache, \
                 patch.object(upstream.asyncio, "sleep", AsyncMock()):
                with self.assertRaises(HTTPException) as caught:
                    await catalog_service.cached_shiki("animes/1735")
            self.assertEqual(caught.exception.status_code, code)
            cache.assert_not_awaited()
