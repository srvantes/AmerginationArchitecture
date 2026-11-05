"""Kodik's permitted public integration, independent of AnimeGo and title search."""
import asyncio
import hashlib
import re

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.core.cache import get_cached_json, set_cached_json
from backend.core.config import settings
from backend.services.player_catalogs import kodik

TTL = 600
_inflight = {}
_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_HASH = re.compile(r"[0-9a-f]{16,64}\Z")


class Voice(BaseModel):
    id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    name: str = Field(min_length=1, max_length=200)
    kind: str | None = None
    embed_url: str

    @field_validator("embed_url")
    @classmethod
    def trusted_embed(cls, value):
        if kodik._checked_url(value)[1] != "serial":
            raise ValueError("Expected a serial")
        return value


class Title(BaseModel):
    translations: list[Voice] = Field(min_length=1, max_length=100)
    season: str = Field(pattern=r"^[1-9][0-9]{0,5}$")
    episodes: list[int]

    @field_validator("episodes")
    @classmethod
    def exact_numbers(cls, value):
        if len(value) > kodik.MAX_EPISODES or any(not 1 <= number <= 100000 for number in value):
            raise ValueError("Invalid episodes")
        return sorted(set(value))


class VoiceEpisodes(BaseModel):
    translation: Voice
    episodes: dict[int, str]

    @field_validator("episodes")
    @classmethod
    def trusted_episodes(cls, value):
        if len(value) > kodik.MAX_EPISODES:
            raise ValueError("Too many episodes")
        for number, embed in value.items():
            if not 1 <= number <= 100000 or kodik._checked_url(embed)[1] != "seria":
                raise ValueError("Invalid episode")
        return value


def _serial(media_id, media_hash):
    if not _ID.fullmatch(media_id or "") or not _HASH.fullmatch(media_hash or ""):
        raise kodik._invalid()
    return f"{kodik.ORIGIN}/serial/{media_id}/{media_hash}/720p"


def _voices(soup):
    options = soup.select(".serial-translations-box select option")
    if not options or len(options) > 100:
        raise kodik._invalid()
    voices, selected = {}, []
    for option in options:
        if option.has_attr("disabled"):
            continue
        if option.get("data-media-type") != "serial":
            raise kodik._invalid()
        voice = Voice(id=option.get("data-id"), name=option.get("data-title"),
                      kind=option.get("data-translation-type"),
                      embed_url=_serial(option.get("data-media-id"), option.get("data-media-hash")))
        if voice.id in voices:
            raise kodik._invalid()
        voices[voice.id] = voice
        if option.has_attr("selected"):
            selected.append(voice.id)
    if not voices or len(selected) != 1:
        raise kodik._invalid()
    return list(voices.values()), selected[0]


def _season(soup):
    options = soup.select(".serial-seasons-box select option[selected]")
    if len(options) != 1 or options[0].get("data-other-translation") != "false":
        raise kodik._invalid()
    value = options[0].get("value", "")
    if not re.fullmatch(r"[1-9][0-9]{0,5}", value):
        raise kodik._invalid()
    return value


def _client():
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.EXTERNAL_READ_TIMEOUT_SECONDS,
                              connect=settings.EXTERNAL_CONNECT_TIMEOUT_SECONDS),
        follow_redirects=False, trust_env=False,
        headers={"User-Agent": "Mozilla/5.0", "Referer": kodik._site_origin() + "/"})


async def _load_title(shikimori_id):
    async with _client() as client:
        url = await kodik._public_serial(client, shikimori_id)
        if url is None:
            raise HTTPException(404, "В Kodik пока не найден этот сериал")
        soup = BeautifulSoup(await kodik._body(client, url), "html.parser")
        voices, _ = _voices(soup)
        return Title(translations=voices, season=_season(soup), episodes=kodik._numbers(soup))


async def _load_voice(shikimori_id, translation_id):
    title = await get_title(shikimori_id)
    voice = next((voice for voice in title.translations if voice.id == translation_id), None)
    if voice is None:
        raise HTTPException(404, "Озвучка Kodik не найдена")
    async with _client() as client:
        soup = BeautifulSoup(await kodik._body(client, voice.embed_url), "html.parser")
        if _season(soup) != title.season:
            # A studio's default can be another season. Follow only the season
            # explicitly identified by the Shikimori-bound public player.
            options = [option for option in soup.select(".serial-seasons-box select option")
                       if option.get("value") == title.season
                       and option.get("data-other-translation") == "false"]
            if len(options) != 1:
                raise HTTPException(404, "Сезон недоступен в выбранной озвучке Kodik")
            option = options[0]
            url = _serial(option.get("data-serial-id"), option.get("data-serial-hash"))
            soup = BeautifulSoup(await kodik._body(client, url), "html.parser")
        _, selected = _voices(soup)
        if selected != translation_id or _season(soup) != title.season:
            raise kodik._invalid()
        numbers = set(kodik._numbers(soup))
        episodes = {}
        for option in soup.select(".serial-series-box select option"):
            number = int(option["value"])
            if number not in numbers:
                continue
            serial = _serial(option.get("data-id"), option.get("data-hash"))
            # Supplied for the whole season: no per-episode availability probes.
            embed = serial.replace("/serial/", "/seria/", 1)
            if number in episodes and episodes[number] != embed:
                raise kodik._invalid()
            episodes[number] = embed
        return VoiceEpisodes(translation=voice, episodes=episodes)


async def _cached(kind, shikimori_id, model, loader, translation_id=None):
    for value in [shikimori_id, *([translation_id] if translation_id is not None else [])]:
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise HTTPException(422, "Некорректный ID Kodik или Shikimori")
    origin = hashlib.sha256(kodik._site_origin().encode()).hexdigest()[:16]
    key = f"kodik:direct:v1:{origin}:{kind}:{shikimori_id}:{translation_id or ''}"
    cached = await get_cached_json(key)
    if cached is not None:
        try:
            value = model.model_validate(cached)
            if isinstance(value, VoiceEpisodes) and value.translation.id != translation_id:
                raise ValueError("Cached translation mismatch")
            return value
        except (ValueError, HTTPException):
            pass
    task_key = (asyncio.get_running_loop(), key)
    task = _inflight.get(task_key)
    if task is None:
        if len(_inflight) >= 8:
            raise HTTPException(503, "Каталоги Kodik сейчас загружаются. Повторите чуть позже.")

        async def run():
            try:
                async with asyncio.timeout(settings.EXTERNAL_SERVICE_TIMEOUT_SECONDS):
                    value = await loader()
                    await set_cached_json(key, TTL, value.model_dump(mode="json"))
                    return value
            except HTTPException:
                raise
            except (TimeoutError, httpx.TimeoutException):
                raise HTTPException(504, "Kodik не ответил вовремя") from None
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                raise HTTPException(502, "Каталог Kodik временно недоступен") from None

        task = asyncio.create_task(run())
        _inflight[task_key] = task

        def finished(completed):
            _inflight.pop(task_key, None)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)
    return await asyncio.shield(task)


async def get_title(shikimori_id):
    return await _cached("title", shikimori_id, Title, lambda: _load_title(shikimori_id))


async def get_voice(shikimori_id, translation_id):
    return await _cached("voice", shikimori_id, VoiceEpisodes,
                         lambda: _load_voice(shikimori_id, translation_id), translation_id)
