"""Exact episode numbers from Kodik metadata, with no individual episode probing.

Known serial embeds work without a token. AnimeGo's usual /seria/ embeds use
a trusted Shikimori ID and either the configured project API key or Kodik's
official public browser autoembed integration. The latter respects the site's
allowed flag before reading its serial URL. Public integration credentials
remain only in memory; third-party token lists are never accessed. Do not guess
media IDs or infer episode ranges from translation names.
"""
import asyncio
import hashlib
import json
import re
import time
import unicodedata
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException

from backend.core.config import settings
from backend.core.cache import get_cached_json, set_cached_json


ORIGIN = "https://kodikplayer.com"
EMBED_PATH = re.compile(r"/(serial|seria)/([1-9][0-9]{0,15})/([0-9a-f]{16,64})(?:/(?:360|480|720|1080)p)?/?\Z")
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_EPISODES = 10000
MAX_API_BODY_BYTES = 8 * 1024 * 1024
API_SEARCH = "https://kodik-api.com/search"
API_GET_PLAYER = "https://kodik-api.com/get-player"
PUBLIC_SCRIPT = "https://kodik-add.com/add-players.min.js?v=2"
API_MEDIA_HOSTS = {"kodikplayer.com", "kodik.info"}
_integration_token: tuple[float, str] | None = None


def _invalid():
    return HTTPException(502, "Kodik вернул некорректные метаданные серий")


def _unsupported(detail="Для отдельной серии Kodik не найден полный каталог; нужна ссылка на сериал"):
    return HTTPException(501, detail)


def _checked_url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value):
        raise _invalid()
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname == "kodikplayer.com"
                 and parsed.port in (None, 443) and parsed.username is None
                 and parsed.password is None and not parsed.fragment)
    except ValueError:
        raise _invalid() from None
    match = EMBED_PATH.fullmatch(parsed.path) if valid else None
    if match is None:
        raise _invalid()
    return match


def _name(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _translation(soup, translation_name, translation_id=None):
    options = soup.select(".serial-translations-box select option")
    if not options:
        raise _invalid()
    matches = []
    for option in options:
        if translation_id is not None:
            if option.get("data-id") == translation_id:
                matches.append(option)
            continue
        title = option.get("data-title")
        if not isinstance(title, str):
            # The visible label may append a count/range; use it only as a name.
            title = re.sub(r"\s*\([^)]*\sэп\.\)\s*$", "", option.get_text(" ", strip=True))
        if _name(title) == _name(translation_name):
            matches.append(option)
    if not matches:
        return None
    if len(matches) != 1:
        raise _unsupported("Не удалось однозначно найти выбранную озвучку в каталоге Kodik")
    option = matches[0]
    media_id, media_hash = option.get("data-media-id"), option.get("data-media-hash")
    if option.get("data-media-type") != "serial":
        raise _unsupported()
    if (not isinstance(media_id, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", media_id)
            or not isinstance(media_hash, str) or not re.fullmatch(r"[0-9a-f]{16,64}", media_hash)):
        raise _invalid()
    return option, media_id, media_hash


def _reference_translation_id(body):
    """Read the provider's ID from the known episode, without executing JS.

    AnimeGo's display label can be an alias or a generic dubbing description.
    Kodik declares its own ID twice on some embeds; both must agree.
    """
    soup = BeautifulSoup(body, "html.parser")
    values = set()
    for script in soup.find_all("script", src=False):
        values.update(re.findall(r"\bvar\s+translationId\s*=\s*([1-9][0-9]{0,15})\s*;",
                                 script.get_text()))
    if len(values) != 1:
        raise _invalid()
    return values.pop()


def _numbers(soup):
    options = soup.select(".serial-series-box select option")
    if not options or len(options) > MAX_EPISODES:
        raise _invalid()
    numbers = set()
    for option in options:
        other_translation = option.get("data-other-translation")
        if other_translation not in {"true", "false"}:
            # Kodik can substitute another studio for missing episodes.
            # Do not silently count entries whose ownership cannot be verified.
            raise _invalid()
        if other_translation == "true" or option.has_attr("disabled"):
            continue
        value = option.get("value")
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,5}", value):
            raise _invalid()
        number = int(value)
        if number > 100000:
            raise _invalid()
        numbers.add(number)
    return sorted(numbers)


async def _body(client, url):
    async def fetch():
        _checked_url(url)
        async with client.stream("GET", url, follow_redirects=False) as response:
            if 300 <= response.status_code < 400:
                raise _invalid()
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BODY_BYTES:
                    raise _invalid()
            return bytes(body)
    return await fetch()


def _api_media_identity(link):
    """Validate returned links without following or downloading any episode URL."""
    if not isinstance(link, str) or len(link) > 4096 or any(ord(c) < 33 for c in link):
        raise _invalid()
    if link.startswith("//"):
        link = "https:" + link
    try:
        parsed = urlsplit(link)
        valid = (parsed.scheme == "https" and parsed.hostname in API_MEDIA_HOSTS
                 and parsed.port in (None, 443) and parsed.username is None
                 and parsed.password is None and not parsed.fragment)
    except ValueError:
        raise _invalid() from None
    match = EMBED_PATH.fullmatch(parsed.path) if valid else None
    if match is None or match[1] != "seria":
        raise _invalid()
    return match[2], match[3]


def _api_numbers(data, shikimori_id, translation_name, original_match):
    if not isinstance(data, dict) or data.get("error"):
        raise HTTPException(502, "API Kodik не принял запрос каталога; проверьте настроенный ключ")
    results = data.get("results")
    if (not isinstance(results, list) or len(results) > 100 or data.get("next_page")
            or type(data.get("total")) is not int or data["total"] != len(results)):
        # Never present the first page as the complete translation catalog.
        raise _invalid()
    matched, reference_matched = [], []
    for item in results:
        if (not isinstance(item, dict) or str(item.get("shikimori_id")) != shikimori_id
                or not isinstance(item.get("translation"), dict)
                or not isinstance(item["translation"].get("title"), str)):
            raise _invalid()
        if _name(item["translation"]["title"]) == _name(translation_name):
            matched.append(item)
        # The reference episode is stronger evidence than a display-name alias.
        # API episode links identify both the translation and its season.
        seasons = item.get("seasons")
        if isinstance(seasons, dict):
            for season in seasons.values():
                episodes = season.get("episodes") if isinstance(season, dict) else None
                if not isinstance(episodes, dict):
                    continue
                if len(episodes) > MAX_EPISODES:
                    raise _invalid()
                if any(_api_media_identity(episode.get("link") if isinstance(episode, dict) else episode)
                       == (original_match[2], original_match[3]) for episode in episodes.values()):
                    reference_matched.append(item)
                    break
    matched = reference_matched or matched
    if not matched:
        return []
    if len(matched) != 1:
        raise _unsupported("API Kodik вернул несколько каталогов выбранной озвучки")
    seasons = matched[0].get("seasons")
    if not isinstance(seasons, dict) or not seasons or len(seasons) > 100:
        raise _invalid()
    season_numbers = []
    original_seasons = []
    for season in seasons.values():
        if not isinstance(season, dict) or not isinstance(season.get("episodes"), dict):
            raise _invalid()
        episodes = season["episodes"]
        if len(episodes) > MAX_EPISODES:
            raise _invalid()
        numbers = set()
        includes_original = False
        for number, episode in episodes.items():
            if not isinstance(number, str) or not re.fullmatch(r"[0-9]{1,6}", number) or int(number) > 100000:
                raise _invalid()
            link = episode.get("link") if isinstance(episode, dict) else episode
            media_id, media_hash = _api_media_identity(link)
            includes_original |= (media_id, media_hash) == (original_match[2], original_match[3])
            if int(number) > 0:
                numbers.add(int(number))
        season_numbers.append(numbers)
        if includes_original:
            original_seasons.append(numbers)
    if len(original_seasons) == 1:
        return sorted(original_seasons[0])
    if len(original_seasons) > 1:
        raise _invalid()
    combined = set()
    for numbers in season_numbers:
        if combined.intersection(numbers):
            raise _unsupported("У сезонов Kodik пересекается нумерация; исходная серия не определяет сезон")
        combined.update(numbers)
    return sorted(combined)


async def _from_api(client, shikimori_id, translation_name, original_match, token):
    # The configured key is sent only to the fixed provider origin in a POST
    # body. No token-bearing URLs, redirects, response snippets or key logging.
    async with client.stream("POST", API_SEARCH, follow_redirects=False, data={
        "token": token, "shikimori_id": shikimori_id, "limit": "100", "with_episodes": "true",
    }) as response:
        if 300 <= response.status_code < 400:
            raise _invalid()
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_API_BODY_BYTES:
                raise _invalid()
    return _api_numbers(json.loads(body), shikimori_id, translation_name, original_match)


def _site_origin():
    value = settings.KODIK_SITE_URL
    if not isinstance(value, str) or any(ord(c) < 33 for c in value):
        raise _unsupported("Некорректно настроен адрес сайта для интеграции Kodik")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                 and parsed.username is None and parsed.password is None
                 and not parsed.query and not parsed.fragment and parsed.path in {"", "/"})
        parsed.port  # Validate malformed port values without echoing the URL.
    except ValueError:
        raise _unsupported("Некорректно настроен адрес сайта для интеграции Kodik") from None
    if not valid:
        raise _unsupported("Некорректно настроен адрес сайта для интеграции Kodik")
    return f"{parsed.scheme}://{parsed.netloc}"


async def _integration_body(client, method, url, max_bytes, **kwargs):
    # Targets are hardcoded provider-owned endpoints, never extracted JS URLs.
    if (method, url) not in {("GET", PUBLIC_SCRIPT), ("POST", API_GET_PLAYER)}:
        raise _invalid()
    async with client.stream(method, url, follow_redirects=False, **kwargs) as response:
        if 300 <= response.status_code < 400:
            raise _invalid()
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > max_bytes:
                raise _invalid()
    return bytes(body)


async def _public_integration_token(client, referer):
    global _integration_token
    if _integration_token is not None and _integration_token[0] > time.monotonic():
        return _integration_token[1]
    body = await _integration_body(client, "GET", PUBLIC_SCRIPT, 256 * 1024,
                                   headers={"Referer": referer})
    script = body.decode("utf-8")
    # This is the provider's own public browser autoembed integration. Its r.token
    # is intentionally shipped to every browser and used by window.kodikAddPlayers.
    # Do not execute JS, load external token lists, or persist this value anywhere.
    matches = re.findall(r'\br\.token\s*=\s*"([A-Za-z0-9_-]{16,128})"', script)
    if (len(matches) != 1 or "window.kodikAddPlayers" not in script
            or API_GET_PLAYER not in script):
        raise _unsupported("Публичная интеграция Kodik изменилась; требуется обновить подключение")
    _integration_token = (time.monotonic() + 3600, matches[0])
    return matches[0]


async def _public_serial(client, shikimori_id):
    origin = _site_origin()
    site_key = hashlib.sha256(origin.encode()).hexdigest()[:16]
    cache_key = f"kodik:public-serial:v1:{site_key}:{shikimori_id}"
    cached = await get_cached_json(cache_key)
    if isinstance(cached, str):
        try:
            if _checked_url(cached)[1] == "serial":
                return cached
        except HTTPException:
            pass
    token = await _public_integration_token(client, origin + "/")
    body = await _integration_body(client, "POST", API_GET_PLAYER, MAX_BODY_BYTES, data={
        "title": "Player", "hasPlayer": "false", "url": origin + "/anime/shikimori/" + shikimori_id,
        "shikimoriID": shikimori_id, "token": token,
    }, headers={"Referer": origin + "/"})
    data = json.loads(body)
    if not isinstance(data, dict) or data.get("error"):
        raise HTTPException(502, "Публичная интеграция Kodik временно недоступна")
    # Respect the same strict allowed===1 condition as the official browser JS.
    # A denied link is never opened, cached, or retried under another site origin.
    if type(data.get("allowed")) is not int or data["allowed"] != 1:
        raise _unsupported("Kodik не разрешил подключение плеера для настроенного адреса сайта")
    if data.get("found") is False:
        return None
    if data.get("found") is not True or not isinstance(data.get("link"), str):
        raise _invalid()
    link = data["link"]
    if link.startswith("//"):
        link = "https:" + link
    if _checked_url(link)[1] != "serial":
        raise _unsupported("Публичная интеграция Kodik не вернула каталог сериала")
    await set_cached_json(cache_key, 1800, link)
    return link


async def get_episode_numbers(embed_url: str, translation_name: str, *, shikimori_id: str | None = None) -> list[int]:
    """Read whole-title metadata, never request each episode to test availability."""
    match = _checked_url(embed_url)
    if not isinstance(translation_name, str) or not 1 <= len(translation_name.strip()) <= 200:
        raise _invalid()
    if match[1] == "seria":
        if shikimori_id is None:
            raise _unsupported("Для каталога отдельной серии Kodik нужна подтверждённая связь с Shikimori")
        if not isinstance(shikimori_id, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", shikimori_id):
            raise _invalid()
    # Ignore input query switches (e.g. translations=false) so metadata remains
    # visible. Both targets below are built from validated media IDs and hashes.
    url = f"{ORIGIN}/serial/{match[2]}/{match[3]}/720p"
    try:
        async with asyncio.timeout(settings.EXTERNAL_SERVICE_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(settings.EXTERNAL_READ_TIMEOUT_SECONDS,
                                      connect=settings.EXTERNAL_CONNECT_TIMEOUT_SECONDS),
                follow_redirects=False, trust_env=False,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://animego.me/"},
            ) as client:
                if match[1] == "seria":
                    if settings.KODIK_TOKEN:
                        return await _from_api(client, shikimori_id, translation_name, match, settings.KODIK_TOKEN)
                    serial_url = await _public_serial(client, shikimori_id)
                    if serial_url is None:
                        return []
                    match = _checked_url(serial_url)
                    url = f"{ORIGIN}/serial/{match[2]}/{match[3]}/720p"
                soup = BeautifulSoup(await _body(client, url), "html.parser")
                translation = _translation(soup, translation_name)
                translation_id = None
                if translation is None and _checked_url(embed_url)[1] == "seria":
                    # One already known reference episode identifies its studio.
                    # This is metadata lookup, never scanning/probing episodes.
                    translation_id = _reference_translation_id(await _body(client, embed_url))
                    translation = _translation(soup, translation_name, translation_id)
                if translation is None:
                    return []
                option, media_id, media_hash = translation
                if (media_id, media_hash) != (match[2], match[3]):
                    url = f"{ORIGIN}/serial/{media_id}/{media_hash}/720p"
                    soup = BeautifulSoup(await _body(client, url), "html.parser")
                    translation = _translation(soup, translation_name, translation_id)
                    if translation is None:
                        return []
                    option, resolved_id, resolved_hash = translation
                    if (resolved_id, resolved_hash) != (media_id, media_hash):
                        raise _invalid()
                if not option.has_attr("selected"):
                    raise _invalid()
                return _numbers(soup)
    except HTTPException:
        raise
    except (asyncio.TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, "Kodik не ответил вовремя") from None
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(502, "Каталог серий Kodik временно недоступен") from None
