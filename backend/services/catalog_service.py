"""Live catalog with conservative, explicit matching between provider IDs."""
import asyncio
import logging
import re
from urllib.parse import urlparse

import httpx
import requests
from fastapi import HTTPException

from backend.core.cache import get_cached_json, set_cached_json
from backend.core.config import settings
from backend.services.upstream import run_async
from backend.database.sсhemas.catalog import (
    AnimeCard, AnimeDetails, RelatedAnime, PlaybackMatch, CatalogPage, HomeCatalog,
)
from backend.services.animego_service import _parser, _run_sync, _search_words, search_animego
from backend.services.catalog_adapters import number

log = logging.getLogger(__name__)
SHIKI = "https://shikimori.io"
KIND = {"tv": "Сериал", "movie": "Фильм", "ova": "OVA", "ona": "ONA", "special": "Спешл", "music": "Клип", "tv_special": "Спешл"}


async def shiki_request(path, params=None):
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.EXTERNAL_READ_TIMEOUT_SECONDS,
                                                    connect=settings.EXTERNAL_CONNECT_TIMEOUT_SECONDS),
                                 headers={"User-Agent": "Amergination/1.0"}) as client:
        try:
            async def fetch():
                response = await client.get(SHIKI + "/api/" + path, params=params)
                if response.status_code == 404:
                    raise HTTPException(404, "Аниме не найдено на Shikimori")
                response.raise_for_status()
                return response
            response = await run_async(fetch, "Shikimori")
            return response.json()
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise HTTPException(504, "Shikimori не ответил вовремя")
        except (httpx.HTTPError, ValueError):
            log.warning("Shikimori catalog request failed")
            raise HTTPException(502, "Каталог Shikimori временно недоступен")


async def cached_shiki(path, params=None, ttl=21600):
    key = "catalog:shiki:v1:" + path + ":" + str(sorted((params or {}).items()))
    cached = await get_cached_json(key)
    if cached is not None:
        return cached
    data = await shiki_request(path, params)
    await set_cached_json(key, ttl, data)
    return data


def shiki_card(data):
    return AnimeCard(
        source="shikimori", external_id=str(data["id"]), title=data.get("russian") or data["name"],
        original_title=data.get("name"), page_url=SHIKI + data["url"],
        poster_url=SHIKI + data["image"]["original"] if data.get("image", {}).get("original") else None,
        year=number((data.get("aired_on") or "")[:4]), kind=KIND.get(data.get("kind"), data.get("kind")),
        status=data.get("status"), score=number(data.get("score"), float),
        genres=[genre.get("russian") or genre["name"] for genre in data.get("genres", [])],
    )


async def home_catalog(limit):
    # Independent shelves stay available when one provider request fails.
    results = await asyncio.gather(
        cached_shiki("animes", {"status": "ongoing", "kind": "tv,ona", "order": "popularity", "limit": limit}, ttl=1800),
        cached_shiki("animes", {"status": "released", "kind": "tv,movie,ona", "order": "ranked", "limit": limit}, ttl=21600),
        return_exceptions=True,
    )
    shelves, warnings = [], []
    for name, result in zip(("Онгоинги", "Популярные аниме"), results):
        if isinstance(result, Exception):
            warnings.append(name + ": источник временно недоступен")
            shelves.append([])
        else:
            shelves.append([shiki_card(item) for item in result])
    if len(warnings) == 2:
        raise HTTPException(502, "Каталог временно недоступен. Попробуйте позже.")
    return HomeCatalog(ongoing=shelves[0], popular=shelves[1], warnings=warnings)


def matching_cards(reference, candidates):
    """A name match alone is insufficient: require year and kind as well."""
    names = {tuple(_search_words(name)) for name in [reference.title, reference.original_title] if name}
    return [card for card in candidates if reference.year is not None and reference.kind is not None
            and card.year == reference.year and card.kind == reference.kind
            and names.intersection(tuple(_search_words(name)) for name in [card.title, card.original_title] if name)]


async def animego_match(details):
    from backend.services.catalog_adapters import anime_card
    raw = await search_animego(details.original_title or details.title)
    matches = matching_cards(details, [anime_card(item, "animego") for item in raw])
    if not matches and details.original_title:
        raw = await search_animego(details.title)
        matches = matching_cards(details, [anime_card(item, "animego") for item in raw])
    matches = list({card.external_id: card for card in matches}.values())
    if len(matches) != 1:
        return PlaybackMatch(status="ambiguous" if matches else "not_found", shikimori_id=details.external_id)
    match = matches[0]
    await set_cached_json("catalog:animego:card:" + match.external_id, 86400, match.model_dump(mode="json"))
    return PlaybackMatch(status="matched", animego_id=match.external_id, shikimori_id=details.external_id, method="title_year_kind")


async def shiki_page(external_id, known_animego_id=None):
    data = await cached_shiki("animes/" + external_id)
    card = shiki_card(data)
    details = AnimeDetails(**card.model_dump(), description=data.get("description") or None,
                           episodes_total=data.get("episodes") or None, episodes_aired=data.get("episodes_aired"),
                           episode_duration=str(data["duration"]) + " мин." if data.get("duration") else None,
                           age_rating=data.get("rating"), dates=data.get("aired_on"))
    async def resolve_playback():
        if known_animego_id:
            return PlaybackMatch(status="matched", animego_id=known_animego_id,
                                 shikimori_id=external_id, method="same_source")
        return await animego_match(details)

    related_raw, match = await asyncio.gather(cached_shiki("animes/" + external_id + "/related"), resolve_playback(), return_exceptions=True)
    warnings, related = [], []
    if isinstance(related_raw, Exception):
        warnings.append("Связанные тайтлы временно недоступны")
    else:
        related = [RelatedAnime(**shiki_card(item["anime"]).model_dump(), relation=item.get("relation_russian"))
                   for item in related_raw if item.get("anime")]
    if isinstance(match, Exception):
        warnings.append("Не удалось проверить доступность плеера")
        match = PlaybackMatch(status="unavailable", shikimori_id=external_id)
    return CatalogPage(details=details, related=related, playback=match, warnings=warnings)


async def animego_page(external_id, slug):
    card_data = await get_cached_json("catalog:animego:card:" + external_id)
    if slug:
        # Construct the URL ourselves; callers cannot make arbitrary HTTP requests.
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise HTTPException(422, "Некорректный slug AnimeGo")
        page_url = _parser._ANIMEGO_BASE + "/anime/" + slug + "-" + external_id
    elif card_data:
        page_url = card_data["page_url"]
    else:
        raise HTTPException(404, "Откройте тайтл через поиск: для AnimeGo нужен slug страницы")
    try:
        raw = await _run_sync(_parser.anime_info, page_url)
    except (asyncio.TimeoutError, requests.Timeout):
        raise HTTPException(504, "AnimeGo не ответил вовремя")
    except Exception:
        log.warning("AnimeGo details failed for %s", external_id)
        raise HTTPException(502, "Описание AnimeGo временно недоступно")
    # Title containers can include synonyms; use the known search title when possible.
    from backend.services.catalog_adapters import anime_card
    if not card_data:
        raw_cards = await search_animego(raw["title"].split("\n")[0])
        card_data = next((anime_card(item, "animego").model_dump(mode="json") for item in raw_cards if str(item["id"]) == external_id), None)
    if not card_data:
        raise HTTPException(502, "Не удалось определить карточку AnimeGo")
    card = AnimeCard.model_validate(card_data)
    details = AnimeDetails(**{**card.model_dump(), "genres": raw.get("genres") or [], "studio": raw.get("studio"), "status": raw.get("status")},
                           description=raw.get("description") or None, episode_duration=raw.get("duration"), age_rating=raw.get("mpaa_rating"))
    related = []
    for item in raw.get("related") or []:
        path = urlparse(item["link"]).path
        found = re.fullmatch(r"/anime/(.+)-([1-9][0-9]*)/?", path)
        if found:
            related.append(RelatedAnime(source="animego", external_id=found[2], slug=found[1], title=item["title"],
                                        page_url=item["link"], poster_url=item.get("image"), year=number(item.get("year")), kind=item.get("type"), relation=item.get("relation")))
    playback = PlaybackMatch(status="matched", animego_id=external_id, method="same_source")
    warnings = []
    try:
        candidates = await cached_shiki("animes", {"search": card.original_title or card.title, "limit": 20})
        matches = matching_cards(card, [shiki_card(item) for item in candidates])
        if len(matches) == 1:
            richer = await shiki_page(matches[0].external_id, known_animego_id=external_id)
            return richer
    except HTTPException:
        warnings.append("Данные Shikimori временно недоступны; показаны данные AnimeGo")
    return CatalogPage(details=details, related=related, playback=playback, warnings=warnings)


async def catalog_page(source, external_id, slug=None):
    key = f"catalog:page:v1:{source}:{external_id}"
    cached = await get_cached_json(key)
    if cached is not None:
        return CatalogPage.model_validate(cached)
    page = await (shiki_page(external_id) if source == "shikimori" else animego_page(external_id, slug))
    if page.details.episodes_total:
        await set_cached_json(f"catalog:progress-total:v1:{page.details.source}:{page.details.external_id}",
                              86400, page.details.episodes_total)
    if not page.warnings and page.playback.status != "unavailable":
        await set_cached_json(key, 21600 if page.playback.status == "matched" else 1800, page.model_dump(mode="json"))
    return page
