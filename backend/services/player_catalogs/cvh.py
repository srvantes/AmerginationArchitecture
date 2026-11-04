"""Read a CVH title playlist once; never inspect individual video streams."""
import asyncio
import re
import unicodedata
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from backend.core.config import settings
from backend.services.upstream import run_async


_EMBED_HOSTS = {"animego.org", "animego.me"}
_EMBED_PATH = re.compile(r"/cdn-iframe/([1-9][0-9]{0,19})/([1-9][0-9]{0,6})/([1-9][0-9]{0,6})/?")
_PLAYLIST_URL = "https://plapi.cdnvideohub.com/api/v1/player/sv/playlist"
_PUBLISHER_ID = "747"
_AGGREGATOR = "mali"


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _embed_context(embed_url: str) -> tuple[str, int, str]:
    """Use only the trusted title/season identifiers, never fetch this URL."""
    try:
        url = urlsplit(embed_url)
        match = _EMBED_PATH.fullmatch(url.path)
        if (url.scheme != "https" or url.hostname not in _EMBED_HOSTS
                or url.username is not None or url.password is not None
                or url.port not in (None, 443) or url.fragment or not match):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=422, detail="Некорректная ссылка CVH от AnimeGo") from None
    return match[1], int(match[2]), f"https://{url.hostname}/"


async def _fetch_playlist(title_id: str, referer: str) -> dict:
    timeout = httpx.Timeout(settings.EXTERNAL_READ_TIMEOUT_SECONDS,
                            connect=settings.EXTERNAL_CONNECT_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        async def request():
            # The destination and path are fixed. Title IDs are query parameters only.
            response = await client.get(
                _PLAYLIST_URL,
                params={"pub": _PUBLISHER_ID, "aggr": _AGGREGATOR, "id": title_id},
                headers={"Referer": referer, "Accept": "application/json",
                         "User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()  # Also rejects redirects without following them.
            return response.json()

        return await run_async(request, provider="CVH")


def _positive_integer(value) -> int:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,6}", value):
        return int(value)
    raise ValueError("Invalid CVH season or episode")


def _episode_numbers(payload, season: int, studio: str, voice_type: str | None) -> list[int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("CVH playlist has no items array")
    matches = []
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid CVH playlist item")
        item_studio = item.get("voiceStudio")
        # Some playlists mix dubbed episodes with records that have no studio.
        # These cannot belong to the explicitly selected studio; do not let an
        # unrelated anonymous record invalidate its whole playlist.
        if item_studio is None or isinstance(item_studio, str) and not item_studio.strip():
            continue
        if not isinstance(item_studio, str):
            raise ValueError("CVH playlist item has no studio")
        if _normalize(item_studio) != studio:
            continue
        item_season = _positive_integer(item.get("season"))
        if item_season != season:
            continue
        item_type = item.get("voiceType")
        if item_type is not None and not isinstance(item_type, str):
            raise ValueError("Invalid CVH voice type")
        normalized_type = _normalize(item_type or "")
        matches.append((normalized_type, _positive_integer(item.get("episode"))))

    available_types = {kind for kind, _ in matches}
    if voice_type is None and len(available_types) > 1:
        raise HTTPException(status_code=502,
                            detail="CVH: у студии несколько типов озвучки; требуется уточнить тип")
    return sorted({episode for kind, episode in matches if voice_type is None or kind == voice_type})


async def get_episode_numbers(embed_url: str, translation_name: str,
                              voice_type: str | None = None) -> list[int]:
    """Return exact episode numbers for one title, season and studio.

    ``voice_type``, when provided, is the exact CVH ``voiceType`` (e.g.
    ``Многоголосый`` or ``Субтитры``), not a fuzzy match or studio substring.
    """
    title_id, season, referer = _embed_context(embed_url)
    if not isinstance(translation_name, str) or not _normalize(translation_name):
        raise HTTPException(status_code=422, detail="Укажите название озвучки CVH")
    if voice_type is not None and (not isinstance(voice_type, str) or not _normalize(voice_type)):
        raise HTTPException(status_code=422, detail="Некорректный тип озвучки CVH")
    try:
        payload = await _fetch_playlist(title_id, referer)
        return _episode_numbers(payload, season, _normalize(translation_name),
                                _normalize(voice_type) if voice_type is not None else None)
    except HTTPException:
        raise
    except (asyncio.TimeoutError, httpx.TimeoutException):
        raise HTTPException(status_code=504, detail="CVH не ответил вовремя") from None
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(status_code=502, detail="Список серий CVH временно недоступен") from None
