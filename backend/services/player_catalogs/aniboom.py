"""Read the exact episode catalog of an Aniboom translation.

The catalog action contains episodes across translations. Only details.available
on the translation-bound, signed endpoint confirms membership. Signed endpoint
URLs are extracted fresh and are never logged or returned to the caller.
"""
import asyncio
import hashlib
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException

from backend.core.config import settings
from backend.core.cache import get_cached_json, set_cached_json
from backend.services.upstream import run_async


ORIGIN = "https://aniboom.one"
ANIMEGO_DOMAINS = {"animego.me", "animego.org"}
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_EPISODES = 10000
BATCH_SIZE = 30
CONCURRENCY = 3
BATCH_CACHE_TTL = 600
DETAILS_START_INTERVAL_SECONDS = 0.2
EMBED_PATH = re.compile(r"/embed/([A-Za-z0-9_-]{1,80})/?\Z")


def _invalid():
    return HTTPException(502, "Aniboom вернул некорректные метаданные серий")


def _checked_url(value: str):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value):
        raise _invalid()
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname == "aniboom.one"
                 and parsed.port in (None, 443) and parsed.username is None
                 and parsed.password is None and not parsed.fragment)
    except ValueError:
        raise _invalid() from None
    if not valid:
        raise _invalid()
    return parsed


def _embed_translation(parsed) -> str:
    """The embed binds an AnimeGo voice to Aniboom's own translation ID."""
    try:
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        values = query.get("translation", [])
        if len(values) != 1 or not re.fullmatch(r"[1-9][0-9]{0,9}", values[0]):
            raise _invalid()
        return values[0]
    except ValueError:
        raise _invalid() from None


def _picker(html: bytes, embed_url: str, anime_id: str, translation_id: str) -> str:
    video = BeautifulSoup(html, "html.parser").select_one("video[data-parameters]")
    if video is None:
        raise _invalid()
    try:
        picker = json.loads(video["data-parameters"])["episodePicker"]
        if (not isinstance(picker, dict) or picker.get("animeId") != anime_id
                or type(picker.get("translation")) is not int
                or str(picker["translation"]) != translation_id):
            raise _invalid()
        endpoint = picker["endpoint"]
        if not isinstance(endpoint, str):
            raise _invalid()
        endpoint = urljoin(embed_url, endpoint)
        parsed = _checked_url(endpoint)
        if parsed.path != f"/embed/{anime_id}/episodes":
            raise _invalid()
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        if (set(query) != {"_expiration", "_hash", "domain", "translation"}
                or any(len(values) != 1 for values in query.values())
                or query["domain"][0] not in ANIMEGO_DOMAINS
                or query["translation"] != [translation_id]
                or not re.fullmatch(r"[0-9]{1,20}", query["_expiration"][0])
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", query["_hash"][0])):
            raise _invalid()
        return endpoint
    except (ValueError, TypeError, KeyError):
        raise _invalid() from None


def _number(value):
    return type(value) is int and 1 <= value <= 100000


async def _body(client: httpx.AsyncClient, method: str, url: str, before_request=None, **kwargs) -> bytes:
    async def fetch():
        # Validate every target, and reject redirects before following any Location.
        _checked_url(url)
        if before_request is not None:
            await before_request()
        async with client.stream(method, url, follow_redirects=False, **kwargs) as response:
            if 300 <= response.status_code < 400:
                raise _invalid()
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BODY_BYTES:
                    raise _invalid()
            return bytes(body)

    return await run_async(fetch, "Aniboom")


async def _catalog(client, endpoint: str, referer: str, anime_id: str, translation_id: str) -> list[int]:
    start_lock, next_start = asyncio.Lock(), 0.0

    async def pace():
        nonlocal next_start
        # A per-operation limiter also covers retry attempts. No global event-loop locks.
        async with start_lock:
            loop = asyncio.get_running_loop()
            remaining = next_start - loop.time()
            if remaining > 0:
                await asyncio.sleep(remaining)
            next_start = loop.time() + DETAILS_START_INTERVAL_SECONDS

    async def request(payload):
        body = await _body(client, "POST", endpoint, json=payload,
                           before_request=pace if payload["action"] == "details" else None,
                           headers={"Referer": referer, "Origin": ORIGIN,
                                    "Accept": "application/json"})
        try:
            data = json.loads(body)
        except (TypeError, ValueError):
            raise _invalid() from None
        if not isinstance(data, dict):
            raise _invalid()
        return data

    numbers = (await request({"action": "catalog"})).get("numbers")
    if (not isinstance(numbers, list) or len(numbers) > MAX_EPISODES
            or any(not _number(number) for number in numbers)):
        raise _invalid()
    numbers = sorted(set(numbers))
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def details(batch):
        async with semaphore:
            digest = hashlib.sha256(json.dumps(batch, separators=(",", ":")).encode("ascii")).hexdigest()
            cache_key = f"aniboom:episode-batch:v1:{anime_id}:{translation_id}:{digest}"
            cached = await get_cached_json(cache_key)
            if (isinstance(cached, dict) and cached.get("checked") == batch
                    and all(_number(number) for number in cached["checked"])
                    and isinstance(cached.get("available"), list)
                    and all(_number(number) and number in batch for number in cached["available"])
                    and len(set(cached["available"])) == len(cached["available"])):
                return cached["available"]
            items = (await request({"action": "details", "numbers": batch})).get("items")
            if not isinstance(items, list) or len(items) != len(batch):
                raise _invalid()
            seen, available = set(), []
            for item in items:
                if (not isinstance(item, dict) or not _number(item.get("episode"))
                        or item["episode"] not in batch or item["episode"] in seen
                        or type(item.get("available")) is not bool):
                    raise _invalid()
                seen.add(item["episode"])
                if item["available"]:
                    available.append(item["episode"])
            # Successful siblings stay useful if a different batch later fails.
            # Cache only a complete, validated batch; never an error or partial result.
            await set_cached_json(cache_key, BATCH_CACHE_TTL, {"checked": batch, "available": available})
            return available

    tasks = [asyncio.create_task(details(numbers[index:index + BATCH_SIZE]))
             for index in range(0, len(numbers), BATCH_SIZE)]
    try:
        batches = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return sorted(number for batch in batches for number in batch)


async def get_episode_numbers(embed_url: str, translation_id: str) -> list[int]:
    """Return exact episode numbers, or a sanitized 502/504; never a partial list."""
    parsed = _checked_url(embed_url)
    match = EMBED_PATH.fullmatch(parsed.path)
    if match is None or not isinstance(translation_id, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", translation_id):
        raise _invalid()
    # AnimeGo and Aniboom IDs differ (e.g. СВ-Дубль: 66 vs 15). The caller
    # already selected the AnimeGo voice; its embed URL identifies the provider
    # translation. Require the signed picker to agree with that exact ID.
    provider_translation = _embed_translation(parsed)
    try:
        # One operation deadline includes all reads, retry delays and queued batches.
        async with asyncio.timeout(settings.EXTERNAL_SERVICE_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(settings.EXTERNAL_READ_TIMEOUT_SECONDS,
                                      connect=settings.EXTERNAL_CONNECT_TIMEOUT_SECONDS),
                limits=httpx.Limits(max_connections=CONCURRENCY, max_keepalive_connections=CONCURRENCY),
                follow_redirects=False, trust_env=False,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://animego.me/"},
            ) as client:
                html = await _body(client, "GET", embed_url)
                endpoint = _picker(html, embed_url, match.group(1), provider_translation)
                return await _catalog(client, endpoint, embed_url, match.group(1), provider_translation)
    except HTTPException:
        raise
    except (asyncio.TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, "Aniboom не ответил вовремя") from None
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(502, "Каталог серий Aniboom временно недоступен") from None
