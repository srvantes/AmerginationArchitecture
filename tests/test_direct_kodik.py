import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.services import direct_kodik as service
from backend.services.player_catalogs import kodik
from main import app


HASH = "a" * 32
HASH_B = "b" * 32
SERIAL = f"https://kodikplayer.com/serial/10/{HASH}/720p"
OTHER_SERIAL = f"https://kodikplayer.com/serial/11/{HASH_B}/720p"


def markup(selected="610", season="2", other=False):
    return f'''<div class="serial-translations-box"><select>
      <option data-id="610" data-title="Studio" data-media-type="serial" data-media-id="10"
        data-media-hash="{HASH}" data-translation-type="voice" {'selected' if selected == '610' else ''}>Studio</option>
      <option data-id="611" data-title="Other" data-media-type="serial" data-media-id="11"
        data-media-hash="{HASH_B}" data-translation-type="voice" {'selected' if selected == '611' else ''}>Other</option>
    </select></div><div class="serial-seasons-box"><select>
      <option value="{season}" selected data-other-translation="false">Season</option>
    </select></div><div class="serial-series-box"><select>
      <option value="1" data-other-translation="false" data-id="20" data-hash="{HASH}">1</option>
      <option value="3" data-other-translation="true" data-id="22" data-hash="{HASH}">3</option>
      <option value="7" data-other-translation="{'true' if other else 'false'}" data-id="21" data-hash="{HASH_B}">7</option>
    </select></div>'''


class DirectKodikTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.get = AsyncMock(return_value=None)
        self.set = AsyncMock()
        for target, name, value in [(service, "get_cached_json", self.get),
                                    (service, "set_cached_json", self.set),
                                    (kodik, "_public_serial", AsyncMock(return_value=SERIAL))]:
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_catalog_and_voice_use_provider_ids_and_exact_sparse_episode_links(self):
        with patch.object(kodik, "_body", AsyncMock(return_value=markup())) as body:
            title = await service.get_title("57779")
            self.assertEqual([v.id for v in title.translations], ["610", "611"])
            self.assertEqual(title.season, "2")
            self.assertEqual(title.episodes, [1, 7])
            with patch.object(service, "get_title", AsyncMock(return_value=title)):
                voice = await service.get_voice("57779", "610")
        self.assertEqual(sorted(voice.episodes), [1, 7])
        self.assertEqual(voice.episodes[7], f"https://kodikplayer.com/seria/21/{HASH_B}/720p")
        self.assertEqual(body.await_count, 2)  # One title and one whole-studio catalogue, no episode probes.
        self.assertEqual([call.args[1] for call in body.await_args_list], [SERIAL, SERIAL])

    async def test_other_studio_is_fetched_by_metadata_not_by_display_name(self):
        title = service.Title(translations=[service.Voice(id="611", name="Other", embed_url=OTHER_SERIAL)],
                              season="2", episodes=[1, 7])
        with patch.object(service, "get_title", AsyncMock(return_value=title)), \
             patch.object(kodik, "_body", AsyncMock(return_value=markup(selected="611"))) as body:
            voice = await service.get_voice("57779", "611")
        self.assertEqual(voice.translation.name, "Other")
        self.assertEqual(body.call_args.args[1], OTHER_SERIAL)

    async def test_studios_default_season_does_not_replace_the_requested_season(self):
        title = service.Title(translations=[service.Voice(id="610", name="Studio", embed_url=SERIAL)],
                              season="2", episodes=[1, 7])
        first = markup(season="1").replace('</select></div><div class="serial-series-box">',
            f'<option value="2" data-other-translation="false" data-serial-id="15" data-serial-hash="{HASH_B}">2</option>'
            '</select></div><div class="serial-series-box">')
        with patch.object(service, "get_title", AsyncMock(return_value=title)), \
             patch.object(kodik, "_body", AsyncMock(side_effect=[first, markup(season="2")])) as body:
            voice = await service.get_voice("57779", "610")
        self.assertEqual(sorted(voice.episodes), [1, 7])
        self.assertEqual(body.await_args_list[1].args[1], f"https://kodikplayer.com/serial/15/{HASH_B}/720p")

    async def test_missing_title_and_denied_integration_are_not_cached(self):
        for failure in [None, HTTPException(501, "Provider denied")]:
            with self.subTest(failure=failure):
                self.set.reset_mock()
                with patch.object(kodik, "_public_serial", AsyncMock(return_value=None,
                                  side_effect=failure if isinstance(failure, Exception) else None)), \
                     patch.object(kodik, "_body", AsyncMock()) as body:
                    with self.assertRaises(HTTPException) as caught:
                        await service.get_title("57779")
                self.assertEqual(caught.exception.status_code, 501 if failure else 404)
                self.set.assert_not_awaited()
                body.assert_not_awaited()

    async def test_invalid_ids_and_missing_studios_never_fetch_a_video(self):
        for identifier in ["0", "1/other", "1?x=y", "01", "x", "1" * 21]:
            with self.subTest(identifier=identifier), self.assertRaises(HTTPException) as caught:
                await service.get_title(identifier)
            self.assertEqual(caught.exception.status_code, 422)
        title = service.Title(translations=[service.Voice(id="610", name="Studio", embed_url=SERIAL)],
                              season="2", episodes=[1, 7])
        with patch.object(service, "get_title", AsyncMock(return_value=title)), \
             patch.object(kodik, "_body", AsyncMock()) as body:
            with self.assertRaises(HTTPException) as caught:
                await service.get_voice("57779", "999")
        self.assertEqual(caught.exception.status_code, 404)
        body.assert_not_awaited()

    async def test_wrong_selected_studio_and_malformed_metadata_fail_closed(self):
        title = service.Title(translations=[service.Voice(id="610", name="Studio", embed_url=SERIAL)],
                              season="2", episodes=[1, 7])
        for html in [markup(selected="611"), markup().replace('data-id="21"', 'data-id="../private"'),
                     markup().replace('data-other-translation="false"', 'data-other-translation="unknown"')]:
            with self.subTest(html=html), patch.object(service, "get_title", AsyncMock(return_value=title)), \
                 patch.object(kodik, "_body", AsyncMock(return_value=html)):
                with self.assertRaises(HTTPException) as caught:
                    await service.get_voice("57779", "610")
            self.assertEqual(caught.exception.status_code, 502)
        self.set.assert_not_awaited()

    async def test_timeout_is_sanitized_and_does_not_poison_cache(self):
        with patch.object(kodik, "_body", AsyncMock(side_effect=httpx.ReadTimeout("private URL"))):
            with self.assertRaises(HTTPException) as caught:
                await service.get_title("57779")
        self.assertEqual(caught.exception.status_code, 504)
        self.assertNotIn("private", caught.exception.detail)
        self.set.assert_not_awaited()

    async def test_concurrent_clients_share_one_title_fetch(self):
        async def body(*args):
            await asyncio.sleep(0)
            return markup()
        with patch.object(kodik, "_body", AsyncMock(side_effect=body)) as fetch:
            results = await asyncio.gather(service.get_title("57779"), service.get_title("57779"))
        self.assertEqual(results[0], results[1])
        fetch.assert_awaited_once()

    async def test_cache_avoids_network_and_wrong_translation_is_rebuilt(self):
        title = service.Title(translations=[service.Voice(id="610", name="Studio", embed_url=SERIAL)],
                              season="2", episodes=[1, 7])
        self.get.return_value = title.model_dump(mode="json")
        with patch.object(kodik, "_body", AsyncMock()) as body:
            self.assertEqual(await service.get_title("57779"), title)
            body.assert_not_awaited()
        wrong = service.VoiceEpisodes(translation=service.Voice(id="611", name="Other", embed_url=OTHER_SERIAL), episodes={})
        self.get.return_value = wrong.model_dump(mode="json")
        with patch.object(service, "get_title", AsyncMock(return_value=title)), \
             patch.object(kodik, "_body", AsyncMock(return_value=markup())) as body:
            result = await service.get_voice("57779", "610")
        self.assertEqual(result.translation.id, "610")
        body.assert_awaited_once()


class DirectKodikEndpointTests(unittest.TestCase):
    def test_routes_keep_shikimori_and_translation_ids_and_reject_unavailable_episode(self):
        title = service.Title(translations=[service.Voice(id="610", name="Studio", embed_url=SERIAL)],
                              season="2", episodes=[1, 7])
        voice = service.VoiceEpisodes(translation=title.translations[0],
                                     episodes={1: SERIAL.replace('/serial/', '/seria/')})
        with TestClient(app) as client, patch.object(service, "get_title", AsyncMock(return_value=title)), \
             patch.object(service, "get_voice", AsyncMock(return_value=voice)) as get_voice:
            catalog = client.get('/api/v1/anime/kodik/catalog', params={'shikimori_id': '57779'})
            self.assertEqual(catalog.status_code, 200, catalog.text)
            self.assertEqual(catalog.json()['translations'][0]['source'], 'kodik')
            self.assertEqual(catalog.json()['id_source'], 'shikimori')
            params = {'shikimori_id': '57779', 'translation_id': '610'}
            episodes = client.get('/api/v1/anime/kodik/voice-episodes', params=params)
            self.assertEqual(episodes.json()['episodes'], [1])
            player = client.get('/api/v1/anime/kodik/player', params={**params, 'episode': 1})
            self.assertEqual(player.status_code, 200, player.text)
            self.assertEqual(player.json()['external_id'], '57779')
            self.assertEqual(player.json()['translation_id'], '610')
            self.assertEqual(player.json()['source'], 'kodik')
            self.assertEqual(client.get('/api/v1/anime/kodik/player', params={**params, 'episode': 7}).status_code, 404)
            get_voice.assert_awaited_with('57779', '610')
