import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from backend.services.player_catalogs import cvh


EMBED = "https://animego.me/cdn-iframe/63293/2/1?dubbing=Jam%20Club"


def record(episode, studio="Jam Club", season=2, voice_type="Многоголосый"):
    return {"cvhId": "public-metadata-id", "name": "", "vkId": "video-id-not-fetched",
            "voiceStudio": studio, "voiceType": voice_type, "season": season, "episode": episode}


class CvhCatalogTests(unittest.IsolatedAsyncioTestCase):
    def client(self, payload=None, status=200, headers=None):
        response = httpx.Response(status, json=payload, headers=headers,
                                  request=httpx.Request("GET", cvh._PLAYLIST_URL))
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = response
        return client

    async def test_exact_sparse_episodes_for_selected_season_and_normalized_studio(self):
        client = self.client({"titleName": "Example", "isSerial": True, "items": [
            record(1), record(3), record(3), record(7), record(2, season=1),
            record(5, studio="Jam Club Extra"), record(8, studio="Other"),
        ]})
        with patch.object(cvh.httpx, "AsyncClient", return_value=client) as factory:
            result = await cvh.get_episode_numbers(EMBED, "  JAM   CLUB  ")
        self.assertEqual(result, [1, 3, 7])
        client.get.assert_awaited_once()
        self.assertEqual(client.get.call_args.args, (cvh._PLAYLIST_URL,))
        self.assertEqual(client.get.call_args.kwargs["params"], {"pub": "747", "aggr": "mali", "id": "63293"})
        self.assertEqual(client.get.call_args.kwargs["headers"]["Referer"], "https://animego.me/")
        self.assertFalse(factory.call_args.kwargs["follow_redirects"])
        self.assertFalse(factory.call_args.kwargs["trust_env"])

    async def test_no_substring_matching_or_inferred_missing_numbers(self):
        with patch.object(cvh, "_fetch_playlist", AsyncMock(return_value={"items": [
                record(1, studio="AniDUB Online"), record(12, studio="AniDUB Online")]})):
            self.assertEqual(await cvh.get_episode_numbers(EMBED, "AniDUB"), [])
            self.assertEqual(await cvh.get_episode_numbers(EMBED, "AniDUB Online"), [1, 12])

    async def test_studio_segment_embeds_use_the_actual_season_and_selected_voice(self):
        cases = [
            ("Dream%20Cast", "Dream Cast"),
            ("AnilibriaTV", "AniLibria"),
            ("%D0%A1%D1%82%D1%83%D0%B4%D0%B8%D0%B9%D0%BD%D0%B0%D1%8F%20%D0%91%D0%B0%D0%BD%D0%B4%D0%B0", "Студийная Банда"),
        ]
        for segment, studio in cases:
            with self.subTest(studio=studio):
                payload = {"items": [record(1, studio=studio, season=1),
                                     record(3, studio=studio, season=1),
                                     record(7, studio=studio, season=2),
                                     record(4, studio=studio + " Extra", season=1)]}
                with patch.object(cvh, "_fetch_playlist", AsyncMock(return_value=payload)) as fetch:
                    result = await cvh.get_episode_numbers(
                        f"https://animego.me/cdn-iframe/52991/{segment}/1/1", studio)
                self.assertEqual(result, [1, 3])
                fetch.assert_awaited_once_with("52991", "https://animego.me/")

    async def test_anonymous_records_do_not_hide_a_named_studios_episodes(self):
        payload = {"items": [record(1), record(1, studio=None), record(3),
                             record(7, studio=""), record(8, studio="   "),
                             record(12, studio="Other"), {"season": 2, "episode": 9}]}
        with patch.object(cvh, "_fetch_playlist", AsyncMock(return_value=payload)):
            self.assertEqual(await cvh.get_episode_numbers(EMBED, "Jam Club"), [1, 3])

    async def test_multiple_voice_types_require_explicit_choice(self):
        payload = {"items": [record(1, voice_type="Дубляж"), record(2), record(3)]}
        with patch.object(cvh, "_fetch_playlist", AsyncMock(return_value=payload)):
            with self.assertRaises(HTTPException) as caught:
                await cvh.get_episode_numbers(EMBED, "Jam Club")
            self.assertEqual(caught.exception.status_code, 502)
            self.assertIn("несколько типов", caught.exception.detail)
            self.assertEqual(await cvh.get_episode_numbers(EMBED, "Jam Club", "Дубляж"), [1])
            self.assertEqual(await cvh.get_episode_numbers(EMBED, "Jam Club", "многоголосый"), [2, 3])

    async def test_untrusted_or_malformed_embeds_never_make_a_request(self):
        invalid = [
            "http://animego.me/cdn-iframe/63293/2/1", "https://127.0.0.1/cdn-iframe/63293/2/1",
            "https://animego.me.evil.example/cdn-iframe/63293/2/1",
            "https://evil.example@animego.me/cdn-iframe/63293/2/1",
            "https://animego.me:444/cdn-iframe/63293/2/1", "https://animego.me:bad/cdn-iframe/63293/2/1",
            "https://animego.me/cdn-iframe/63293/0/1", "https://animego.me/cdn-iframe/x/2/1",
            "https://animego.me/cdn-iframe/63293/2/1/other", "https://animego.me/cdn-iframe/63293/2/1#x",
            "https://animego.me/player/63293", "https://animego.me/cdn-iframe/63293/%32/1",
            "https://animego.me/cdn-iframe/52991/Dream%2FCast/1/1",
            "https://animego.me/cdn-iframe/52991/Dream%5CCast/1/1",
            "https://animego.me/cdn-iframe/52991/%00/1/1",
            "https://animego.me/cdn-iframe/52991/../1/1",
            "https://animego.me/cdn-iframe/52991/Dream%20Cast/0/1",
        ]
        with patch.object(cvh, "_fetch_playlist", AsyncMock()) as fetch:
            for url in invalid:
                with self.subTest(url=url), self.assertRaises(HTTPException) as caught:
                    await cvh.get_episode_numbers(url, "Jam Club")
                self.assertEqual(caught.exception.status_code, 422)
            fetch.assert_not_awaited()

    async def test_redirect_is_rejected_without_contacting_destination(self):
        client = self.client(status=302, headers={"Location": "http://127.0.0.1/private"})
        with patch.object(cvh.httpx, "AsyncClient", return_value=client):
            with self.assertRaises(HTTPException) as caught:
                await cvh.get_episode_numbers(EMBED, "Jam Club")
        self.assertEqual(caught.exception.status_code, 502)
        client.get.assert_awaited_once()

    async def test_invalid_metadata_is_an_error_not_an_empty_list(self):
        for payload in [None, {}, {"items": {}}, {"items": [record(True)]},
                        {"items": [record(1.5)]}, {"items": [record(1, studio=12)]}]:
            with self.subTest(payload=payload), patch.object(cvh, "_fetch_playlist", AsyncMock(return_value=payload)):
                with self.assertRaises(HTTPException) as caught:
                    await cvh.get_episode_numbers(EMBED, "Jam Club")
                self.assertEqual(caught.exception.status_code, 502)
        with patch.object(cvh, "_fetch_playlist", AsyncMock(return_value={"items": []})):
            self.assertEqual(await cvh.get_episode_numbers(EMBED, "Jam Club"), [])

    async def test_timeout_is_mapped_to_gateway_timeout(self):
        with patch.object(cvh, "_fetch_playlist", AsyncMock(side_effect=httpx.ReadTimeout("offline"))):
            with self.assertRaises(HTTPException) as caught:
                await cvh.get_episode_numbers(EMBED, "Jam Club")
        self.assertEqual(caught.exception.status_code, 504)
