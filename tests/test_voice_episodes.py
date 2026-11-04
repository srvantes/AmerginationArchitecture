import asyncio
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.services import voice_catalog as service
from main import app


class VoiceCatalogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.cache = self.stack.enter_context(patch.object(service, "get_cached_json", AsyncMock(return_value=None)))
        self.save = self.stack.enter_context(patch.object(service, "set_cached_json", AsyncMock()))
        self.resolve = self.stack.enter_context(patch.object(service, "get_embedded_player", AsyncMock(return_value={
            "embed": "https://aniboom.one/embed/demo?translation=9", "label": "Studio"})))
        self.adapters = {name: self.stack.enter_context(patch.object(getattr(service, name), "get_episode_numbers", AsyncMock(return_value=[3, 1, 3])))
                         for name in ["aniboom", "cvh", "kodik"]}

    async def test_complete_catalogue_is_loaded_once_and_cached(self):
        result = await service.get_voice_episode_catalog("65", "9", "aniboom", 7)
        self.assertEqual(result["episodes"], [1, 3])
        self.assertEqual(result["status"], "ready")
        self.assertIsNone(result["next_offset"])  # Stops the obsolete paginated client too.
        self.resolve.assert_awaited_once_with("65", 7, "9", "aniboom")
        self.adapters["aniboom"].assert_awaited_once()
        self.save.assert_awaited_once()
        self.assertEqual(self.save.await_args.args[1], 1800)
        self.cache.return_value = result
        self.assertEqual(await service.get_voice_episode_catalog("65", "9", "aniboom", 7), result)
        self.adapters["aniboom"].assert_awaited_once()

    async def test_provider_and_reference_contexts_do_not_share_cache_keys(self):
        await service.get_voice_episode_catalog("65", "9", "aniboom", 1)
        await service.get_voice_episode_catalog("65", "9", "cvh", 1)
        await service.get_voice_episode_catalog("65", "9", "cvh", 2)
        keys = [call.args[0] for call in self.save.await_args_list]
        self.assertEqual(len(set(keys)), 3)
        self.adapters["aniboom"].assert_awaited_once()
        self.assertEqual(self.adapters["cvh"].await_count, 2)

    async def test_invalid_cache_is_rebuilt(self):
        self.cache.return_value = {"status": "ready", "episodes": [True, "3"]}
        result = await service.get_voice_episode_catalog("65", "9", "aniboom")
        self.assertEqual(result["episodes"], [1, 3])
        self.adapters["aniboom"].assert_awaited_once()

    async def test_simultaneous_clients_share_work_and_one_can_disconnect(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def build(*args):
            started.set()
            await finish.wait()
            return [1, 4]
        self.adapters["aniboom"].side_effect = build
        first = asyncio.create_task(service.get_voice_episode_catalog("65", "9", "aniboom"))
        await started.wait()
        second = asyncio.create_task(service.get_voice_episode_catalog("65", "9", "aniboom"))
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        finish.set()
        result = await second
        self.assertEqual(result["episodes"], [1, 4])
        self.adapters["aniboom"].assert_awaited_once()
        self.save.assert_awaited_once()

    async def test_unsupported_provider_never_falls_back_to_episode_probes(self):
        result = await service.get_voice_episode_catalog("65", "9", "sibnet")
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["episodes"], [])
        self.resolve.assert_awaited_once()
        self.save.assert_not_awaited()
        for adapter in self.adapters.values():
            adapter.assert_not_awaited()

    async def test_kodik_single_episode_is_reported_as_unsupported(self):
        self.adapters["kodik"].side_effect = HTTPException(501, "No parent serial")
        result = await service.get_voice_episode_catalog("65", "9", "kodik")
        self.assertEqual(result["status"], "unsupported")
        self.save.assert_not_awaited()

    async def test_kodik_receives_only_server_verified_shikimori_mapping(self):
        async def cached(key):
            return {"shikimori_id": "21"} if key == "catalog:playback-shikimori:v1:65" else None
        self.cache.side_effect = cached
        result = await service.get_voice_episode_catalog("65", "95", "kodik")
        self.assertEqual(result["status"], "ready")
        self.adapters["kodik"].assert_awaited_once_with(
            "https://aniboom.one/embed/demo?translation=9", "Studio", shikimori_id="21")
        self.assertTrue(self.save.await_args.args[0].endswith(":21"))

    async def test_malformed_identity_is_not_passed_to_kodik(self):
        async def cached(key):
            return {"shikimori_id": "https://localhost/private"} if "playback-shikimori" in key else None
        self.cache.side_effect = cached
        await service.get_voice_episode_catalog("65", "95", "kodik")
        self.assertIsNone(self.adapters["kodik"].await_args.kwargs["shikimori_id"])

    async def test_outage_is_not_an_empty_or_cached_catalogue(self):
        self.adapters["aniboom"].side_effect = HTTPException(502, "offline")
        with self.assertRaises(HTTPException) as error:
            await service.get_voice_episode_catalog("65", "9", "aniboom")
        self.assertEqual(error.exception.status_code, 502)
        self.save.assert_not_awaited()

    async def test_total_operation_has_a_deadline(self):
        async def pending(*args):
            await asyncio.Event().wait()
        self.adapters["aniboom"].side_effect = pending
        with patch.object(service.settings, "EXTERNAL_SERVICE_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(HTTPException) as error:
                await service.get_voice_episode_catalog("65", "9", "aniboom")
        self.assertEqual(error.exception.status_code, 504)
        self.save.assert_not_awaited()


class VoiceCatalogContractTests(unittest.TestCase):
    def test_contract_and_parameter_validation(self):
        with TestClient(app) as client, patch("backend.api.v1.endpoints.anime.get_voice_episode_catalog", AsyncMock(
                return_value={"episodes": [1, 3], "status": "ready", "checked": 2, "total": 2, "next_offset": None})) as mock:
            params = {"anime_id": "65", "translation_id": "9", "player": "aniboom", "episode": 7}
            response = client.get("/api/v1/anime/animego/voice-episodes", params=params)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["episodes"], [1, 3])
            mock.assert_awaited_once_with("65", "9", "aniboom", 7)
            for extra in [{"episode": 0}, {"player": "unknown"}, {"translation_id": ""}]:
                self.assertEqual(client.get("/api/v1/anime/animego/voice-episodes", params=params | extra).status_code, 422)
