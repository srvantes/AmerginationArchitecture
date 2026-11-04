import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx
from fastapi import HTTPException

from backend.services.player_catalogs import kodik


HASH_A = "a" * 32
HASH_B = "b" * 32
URL = f"https://kodikplayer.com/serial/10/{HASH_A}/720p"
SERIA = f"https://kodikplayer.com/seria/20/{HASH_A}/720p"
PUBLIC_JS = 'window.kodikAddPlayers;r.token="provider-public-integration-test-key";a.get("https://kodik-api.com/get-player",r);'


def page(selected="Studio", studio_id="10", studio_hash=HASH_A, episode_options=None):
    episode_options = episode_options if episode_options is not None else [
        '<option value="1" data-other-translation="false">1 серия</option>',
        '<option value="4" data-other-translation="true">4 серия, другая студия</option>',
        '<option value="7" data-other-translation="false">7 серия</option>',
    ]
    return f'''<div class="serial-translations-box"><select>
      <option data-media-type="serial" data-media-id="{studio_id}" data-media-hash="{studio_hash}"
        data-title="Studio" {'selected' if selected == 'Studio' else ''}>Studio (1–999 эп.)</option>
      <option data-media-type="serial" data-media-id="11" data-media-hash="{HASH_B}"
        data-title="Other" {'selected' if selected == 'Other' else ''}>Other (24 эп.)</option>
    </select></div><div class="serial-series-box"><select>{''.join(episode_options)}</select></div>'''


class KodikCatalogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cache_get = AsyncMock(return_value=None)
        self.cache_set = AsyncMock()
        for target, name, value in [
            (kodik, "get_cached_json", self.cache_get),
            (kodik, "set_cached_json", self.cache_set),
            (kodik, "_integration_token", None),
            (kodik.settings, "KODIK_SITE_URL", "http://127.0.0.1:8080"),
        ]:
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def call(self, handler, url=URL, name="Studio", **kwargs):
        calls = []
        original = httpx.AsyncClient

        def callback(request):
            calls.append(request)
            return handler(request)

        def client(**kwargs):
            return original(transport=httpx.MockTransport(callback), **kwargs)

        with patch.object(kodik.httpx, "AsyncClient", side_effect=client):
            result = await kodik.get_episode_numbers(url, name, **kwargs)
        return result, calls

    async def test_exact_options_preserve_gaps_and_exclude_other_studio(self):
        result, calls = await self.call(lambda request: httpx.Response(200, text=page()))
        self.assertEqual(result, [1, 7])
        self.assertEqual(len(calls), 1)
        self.assertEqual(str(calls[0].url), URL)

    async def test_switches_translation_from_metadata_in_two_requests(self):
        def response(request):
            return httpx.Response(200, text=page(selected="Studio" if "/10/" in request.url.path else "Other"))

        result, calls = await self.call(response, url=URL + "?translations=false", name="Other")
        self.assertEqual(result, [1, 7])
        self.assertEqual(len(calls), 2)
        self.assertEqual(str(calls[1].url), f"https://kodikplayer.com/serial/11/{HASH_B}/720p")
        self.assertFalse(calls[0].url.query)

    async def test_single_episode_is_unsupported_without_network(self):
        with patch.object(kodik.settings, "KODIK_TOKEN", None), self.assertRaises(HTTPException) as caught:
            await self.call(lambda request: self.fail("must not fetch without a trusted ID"), url=SERIA)
        self.assertEqual(caught.exception.status_code, 501)

    async def test_external_hosts_and_redirects_are_rejected(self):
        for url in [
            URL.replace("kodikplayer.com", "evil.example"),
            URL.replace("https://", "http://"),
            URL.replace("kodikplayer.com", "kodikplayer.com.evil.example"),
            URL.replace("kodikplayer.com", "user@kodikplayer.com"),
            URL.replace("kodikplayer.com", "kodikplayer.com:444"),
            URL + "#fragment",
        ]:
            with self.subTest(url=url), self.assertRaises(HTTPException) as caught:
                await self.call(lambda request: self.fail("unsafe URL requested"), url=url)
            self.assertEqual(caught.exception.status_code, 502)
        requests = []

        def redirect(request):
            requests.append(request)
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

        with self.assertRaises(HTTPException) as caught:
            await self.call(redirect)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(len(requests), 1)

    async def test_unverifiable_ownership_and_wrong_studio_fail_closed(self):
        for markup, name, status in [
            (page(episode_options=['<option value="1">1</option>']), "Studio", 502),
            (page(selected="Other"), "Studio", 502),
            (page(studio_id="../private"), "Studio", 502),
        ]:
            with self.subTest(name=name, markup=markup), self.assertRaises(HTTPException) as caught:
                await self.call(lambda request: httpx.Response(200, text=markup), name=name)
            self.assertEqual(caught.exception.status_code, status)

    async def test_absent_translation_in_serial_is_an_empty_catalog(self):
        result, calls = await self.call(lambda request: httpx.Response(200, text=page()), name="Absent")
        self.assertEqual(result, [])
        self.assertEqual(len(calls), 1)

    async def test_single_episode_resolves_aliased_and_generic_labels_by_provider_id(self):
        self.cache_get.return_value = URL
        for label in ["AniLibria", "Onibaku Group", "Профессиональный многоголосый"]:
            def response(request):
                if request.url.path.startswith("/seria/"):
                    return httpx.Response(200, text='<script>var translationId = 610;</script>'
                                                   '<script>var translationId = 610;</script>')
                markup = page(selected="Other" if "/11/" in request.url.path else "Studio")
                markup = markup.replace('data-title="Other"', 'data-id="610" data-title="Provider name"')
                return httpx.Response(200, text=markup)

            with self.subTest(label=label), patch.object(kodik.settings, "KODIK_TOKEN", None):
                result, calls = await self.call(response, url=SERIA, name=label, shikimori_id="21")
            self.assertEqual(result, [1, 7])
            self.assertEqual([request.url.path.split('/')[1] for request in calls],
                             ["serial", "seria", "serial"])
            self.assertEqual(str(calls[1].url), SERIA)

    async def test_reference_translation_id_must_be_present_and_unambiguous(self):
        self.cache_get.return_value = URL
        for script in ["", "var translationId = 0;", "var translationId = 610; var translationId = 611;"]:
            def response(request):
                return httpx.Response(200, text=f'<script>{script}</script>' if
                                      request.url.path.startswith('/seria/') else page())
            with self.subTest(script=script), patch.object(kodik.settings, "KODIK_TOKEN", None), self.assertRaises(HTTPException) as caught:
                await self.call(response, url=SERIA, name="Alias", shikimori_id="21")
            self.assertEqual(caught.exception.status_code, 502)

    async def test_timeout_http_failure_and_oversized_html_are_sanitized(self):
        def timeout(request):
            raise httpx.ReadTimeout("private URL detail", request=request)

        with self.assertRaises(HTTPException) as caught:
            await self.call(timeout)
        self.assertEqual(caught.exception.status_code, 504)
        self.assertNotIn("private", caught.exception.detail)
        for response in [httpx.Response(503, text="private"),
                         httpx.Response(200, content=b"x" * (kodik.MAX_BODY_BYTES + 1))]:
            with self.subTest(status=response.status_code), self.assertRaises(HTTPException) as caught:
                await self.call(lambda request: response)
            self.assertEqual(caught.exception.status_code, 502)
            self.assertNotIn("private", caught.exception.detail)

    async def test_one_own_key_api_post_returns_exact_episode_keys(self):
        payload = {"total": 2, "results": [
            {"shikimori_id": "21", "translation": {"id": 999, "title": "Other"}, "seasons": {}},
            {"shikimori_id": "21", "translation": {"id": 735, "title": "Studio"}, "seasons": {
                "1": {"episodes": {
                    "1": f"//kodik.info/seria/20/{HASH_A}/720p",
                    "4": {"link": f"//kodik.info/seria/22/{HASH_B}/720p"},
                    "7": f"//kodikplayer.com/seria/23/{HASH_B}/720p",
                }}}},
        ]}
        with patch.object(kodik.settings, "KODIK_TOKEN", "project-test-key"):
            result, calls = await self.call(lambda request: httpx.Response(200, json=payload),
                                            url=SERIA, shikimori_id="21")
        self.assertEqual(result, [1, 4, 7])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].method, "POST")
        self.assertEqual(str(calls[0].url), "https://kodik-api.com/search")
        self.assertNotIn("project-test-key", str(calls[0].url))
        self.assertEqual(parse_qs(calls[0].content.decode()), {
            "token": ["project-test-key"], "shikimori_id": ["21"], "limit": ["100"], "with_episodes": ["true"],
        })

    async def test_api_translation_matching_uses_name_not_animego_id(self):
        payload = {"total": 1, "results": [{"shikimori_id": "21", "translation": {"id": 735, "title": "Other"}, "seasons": {}}]}
        with patch.object(kodik.settings, "KODIK_TOKEN", "project-test-key"):
            result, _ = await self.call(lambda request: httpx.Response(200, json=payload), url=SERIA, shikimori_id="21")
        self.assertEqual(result, [])

    async def test_api_reference_episode_resolves_a_generic_animego_label(self):
        payload = {"total": 2, "results": [
            {"shikimori_id": "21", "translation": {"title": "Профессиональный многоголосый"},
             "seasons": {"1": {"episodes": {"99": f"//kodik.info/seria/99/{HASH_B}/720p"}}}},
            {"shikimori_id": "21", "translation": {"title": "Force Media"},
             "seasons": {"1": {"episodes": {"1": f"//kodik.info/seria/20/{HASH_A}/720p",
                                             "3": f"//kodik.info/seria/23/{HASH_B}/720p"}}}},
        ]}
        with patch.object(kodik.settings, "KODIK_TOKEN", "project-test-key"):
            result, calls = await self.call(lambda request: httpx.Response(200, json=payload),
                                            url=SERIA, name="Профессиональный многоголосый", shikimori_id="21")
        self.assertEqual(result, [1, 3])
        self.assertEqual(len(calls), 1)

    async def test_missing_trusted_id_fails_before_sending_the_key(self):
        with patch.object(kodik.settings, "KODIK_TOKEN", "project-test-key"), self.assertRaises(HTTPException) as caught:
            await self.call(lambda request: self.fail("no trusted ID"), url=SERIA)
        self.assertEqual(caught.exception.status_code, 501)

    async def test_api_original_episode_selects_the_correct_season(self):
        payload = {"total": 1, "results": [{"shikimori_id": "21", "translation": {"title": "Studio"}, "seasons": {
            "1": {"episodes": {"1": f"//kodik.info/seria/50/{HASH_B}/720p", "2": f"//kodik.info/seria/51/{HASH_B}/720p"}},
            "2": {"episodes": {"1": f"//kodik.info/seria/20/{HASH_A}/720p", "3": f"//kodik.info/seria/53/{HASH_B}/720p"}},
        }}]}
        with patch.object(kodik.settings, "KODIK_TOKEN", "project-test-key"):
            result, _ = await self.call(lambda request: httpx.Response(200, json=payload), url=SERIA, shikimori_id="21")
        self.assertEqual(result, [1, 3])
        for season in payload["results"][0]["seasons"].values():
            season["episodes"]["1"] = f"//kodik.info/seria/60/{HASH_B}/720p"
        with patch.object(kodik.settings, "KODIK_TOKEN", "project-test-key"), self.assertRaises(HTTPException) as caught:
            await self.call(lambda request: httpx.Response(200, json=payload), url=SERIA, shikimori_id="21")
        self.assertEqual(caught.exception.status_code, 501)

    async def test_api_rejects_wrong_title_ids_partial_pages_and_secret_errors(self):
        failures = [
            {"error": "project-test-key unauthorized"},
            {"total": 100, "results": [], "next_page": "https://kodik-api.com/search?token=project-test-key"},
            {"total": 1, "results": [{"shikimori_id": "22", "translation": {"title": "Studio"}}]},
        ]
        for payload in failures:
            with self.subTest(payload=payload), patch.object(kodik.settings, "KODIK_TOKEN", "project-test-key"), self.assertRaises(HTTPException) as caught:
                await self.call(lambda request: httpx.Response(200, json=payload), url=SERIA, shikimori_id="21")
            self.assertEqual(caught.exception.status_code, 502)
            self.assertNotIn("project-test-key", caught.exception.detail)

    async def test_api_redirect_is_never_followed_with_the_key(self):
        calls = []

        def redirect(request):
            calls.append(request)
            return httpx.Response(307, headers={"Location": "https://evil.example/token"})

        with patch.object(kodik.settings, "KODIK_TOKEN", "project-test-key"), self.assertRaises(HTTPException) as caught:
            await self.call(redirect, url=SERIA, shikimori_id="21")
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(len(calls), 1)

    async def test_public_autoembed_resolves_single_episode_without_an_own_key(self):
        def response(request):
            if str(request.url) == kodik.PUBLIC_SCRIPT:
                return httpx.Response(200, text=PUBLIC_JS)
            if str(request.url) == kodik.API_GET_PLAYER:
                return httpx.Response(200, json={"allowed": 1, "found": True, "link": URL})
            return httpx.Response(200, text=page())

        with patch.object(kodik.settings, "KODIK_TOKEN", None):
            result, calls = await self.call(response, url=SERIA, shikimori_id="21")
        self.assertEqual(result, [1, 7])
        self.assertEqual([(r.method, str(r.url)) for r in calls], [
            ("GET", kodik.PUBLIC_SCRIPT), ("POST", kodik.API_GET_PLAYER), ("GET", URL),
        ])
        fields = parse_qs(calls[1].content.decode())
        self.assertEqual(fields, {"title": ["Player"], "hasPlayer": ["false"],
            "url": ["http://127.0.0.1:8080/anime/shikimori/21"], "shikimoriID": ["21"],
            "token": ["provider-public-integration-test-key"]})
        self.assertEqual(calls[1].headers["Referer"], "http://127.0.0.1:8080/")
        self.assertTrue(all("provider-public-integration-test-key" not in str(request.url) for request in calls))
        self.cache_set.assert_awaited_once()
        self.assertEqual(self.cache_set.await_args.args[1:], (1800, URL))

    async def test_public_integration_key_is_cached_only_in_runtime_memory(self):
        def response(request):
            if str(request.url) == kodik.PUBLIC_SCRIPT:
                return httpx.Response(200, text=PUBLIC_JS)
            if str(request.url) == kodik.API_GET_PLAYER:
                return httpx.Response(200, json={"allowed": 1, "found": True, "link": URL})
            return httpx.Response(200, text=page())

        with patch.object(kodik.settings, "KODIK_TOKEN", None):
            _, first = await self.call(response, url=SERIA, shikimori_id="21")
            _, second = await self.call(response, url=SERIA, shikimori_id="21")
        self.assertEqual(sum(str(r.url) == kodik.PUBLIC_SCRIPT for r in first + second), 1)
        self.assertNotIn("provider-public-integration-test-key", str(self.cache_set.await_args_list))

    async def test_public_denial_is_respected_before_using_or_caching_a_link(self):
        for allowed in [0, True, "1", 2, None]:
            calls = []

            def response(request):
                calls.append(request)
                if str(request.url) == kodik.PUBLIC_SCRIPT:
                    return httpx.Response(200, text=PUBLIC_JS)
                if str(request.url) == kodik.API_GET_PLAYER:
                    return httpx.Response(200, json={"allowed": allowed, "found": True, "link": URL})
                self.fail("denied serial URL must never be opened")

            with self.subTest(allowed=allowed), patch.object(kodik.settings, "KODIK_TOKEN", None), self.assertRaises(HTTPException) as caught:
                await self.call(response, url=SERIA, shikimori_id="21")
            self.assertEqual(caught.exception.status_code, 501)
            self.cache_set.assert_not_awaited()
            self.assertTrue(all(str(r.url) in {kodik.PUBLIC_SCRIPT, kodik.API_GET_PLAYER} for r in calls))

    async def test_public_not_found_is_empty_and_not_cached(self):
        def response(request):
            if str(request.url) == kodik.PUBLIC_SCRIPT:
                return httpx.Response(200, text=PUBLIC_JS)
            return httpx.Response(200, json={"allowed": 1, "found": False})

        with patch.object(kodik.settings, "KODIK_TOKEN", None):
            result, calls = await self.call(response, url=SERIA, shikimori_id="21")
        self.assertEqual(result, [])
        self.assertEqual(len(calls), 2)
        self.cache_set.assert_not_awaited()

    async def test_cached_serial_link_skips_public_script_and_lookup(self):
        self.cache_get.return_value = URL
        with patch.object(kodik.settings, "KODIK_TOKEN", None):
            result, calls = await self.call(lambda request: httpx.Response(200, text=page()), url=SERIA, shikimori_id="21")
        self.assertEqual(result, [1, 7])
        self.assertEqual([(request.method, str(request.url)) for request in calls], [("GET", URL)])

    async def test_public_cache_and_lookup_use_the_configured_site_origin(self):
        def response(request):
            if str(request.url) == kodik.PUBLIC_SCRIPT:
                return httpx.Response(200, text=PUBLIC_JS)
            if str(request.url) == kodik.API_GET_PLAYER:
                return httpx.Response(200, json={"allowed": 1, "found": True, "link": URL})
            return httpx.Response(200, text=page())

        with patch.object(kodik.settings, "KODIK_TOKEN", None):
            await self.call(response, url=SERIA, shikimori_id="21")
            with patch.object(kodik.settings, "KODIK_SITE_URL", "https://anime.example"):
                _, calls = await self.call(response, url=SERIA, shikimori_id="21")
        keys = [args.args[0] for args in self.cache_set.await_args_list]
        self.assertNotEqual(keys[0], keys[1])
        lookup = next(request for request in calls if str(request.url) == kodik.API_GET_PLAYER)
        self.assertEqual(parse_qs(lookup.content.decode())["url"], ["https://anime.example/anime/shikimori/21"])

    async def test_public_script_or_lookup_redirects_are_never_followed(self):
        for redirect_target in [kodik.PUBLIC_SCRIPT, kodik.API_GET_PLAYER]:
            calls = []

            def response(request):
                calls.append(request)
                if str(request.url) == redirect_target:
                    return httpx.Response(307, headers={"Location": "https://evil.example/collect"})
                return httpx.Response(200, text=PUBLIC_JS)

            with self.subTest(target=redirect_target), patch.object(kodik.settings, "KODIK_TOKEN", None), self.assertRaises(HTTPException) as caught:
                await self.call(response, url=SERIA, shikimori_id="21")
            self.assertEqual(caught.exception.status_code, 502)
            self.assertTrue(all(request.url.host != "evil.example" for request in calls))
            self.cache_set.assert_not_awaited()

    async def test_public_resolver_rejects_changed_script_and_external_serial_links(self):
        with patch.object(kodik.settings, "KODIK_TOKEN", None), self.assertRaises(HTTPException) as caught:
            await self.call(lambda request: httpx.Response(200, text='r.token="provider-public-integration-test-key";'),
                            url=SERIA, shikimori_id="21")
        self.assertEqual(caught.exception.status_code, 501)

        def response(request):
            if str(request.url) == kodik.PUBLIC_SCRIPT:
                return httpx.Response(200, text=PUBLIC_JS)
            return httpx.Response(200, json={"allowed": 1, "found": True, "link": "https://evil.example/serial/1/" + HASH_A})

        with patch.object(kodik.settings, "KODIK_TOKEN", None), self.assertRaises(HTTPException) as caught:
            await self.call(response, url=SERIA, shikimori_id="21")
        self.assertEqual(caught.exception.status_code, 502)
        self.cache_set.assert_not_awaited()
