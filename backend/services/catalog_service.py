"""Live catalog with conservative, explicit matching between provider IDs."""
import asyncio
import hashlib
import json
import logging
import re
from collections import deque
from time import monotonic
from urllib.parse import urlparse
from weakref import WeakKeyDictionary

import httpx
import requests
from fastapi import HTTPException
from pydantic import AnyHttpUrl

from backend.core.cache import get_cached_json, set_cached_json
from backend.core.config import settings
from backend.services.upstream import run_async
from backend.database.sсhemas.catalog import (
    AnimeCard, AnimeDetails, RelatedAnime, PlaybackMatch, CatalogPage, HomeCatalog,
    CatalogCollection, CatalogCollectionInfo,
)
from backend.services.animego_service import _parser, _run_sync, _search_words, search_animego
from backend.services.catalog_adapters import number
from backend.services.posters import poster_url
from backend.services.anime_registry import remember_titles, get_title

log = logging.getLogger(__name__)
SHIKI = "https://shikimori.io"
KIND = {"tv": "Сериал", "movie": "Фильм", "ova": "OVA", "ona": "ONA", "special": "Спешл", "music": "Клип", "tv_special": "Спешл"}
COLLECTION_LIMIT = 50
# IDs were checked against the official GraphQL genres(entryType: Anime).
# /api/genres is the legacy taxonomy and does not contain the Isekai theme.
# REST supports the current taxonomy through the genre_v2 parameter.
THEMATIC_COLLECTIONS = (
    ("shounen", "Сёнен", "27"),
    ("shoujo", "Сёдзё", "25"),
    ("seinen", "Сэйнэн", "42"),
    ("josei", "Дзёсэй", "43"),
    ("fantasy", "Фэнтези", "10"),
    ("comedy", "Комедии", "4"),
    ("drama", "Драмы", "8"),
    ("isekai", "Исекай", "130"),
    ("romance", "Романтика", "22"),
)
_collection_info = {
    "ongoing": CatalogCollectionInfo(slug="ongoing", title="Онгоинги", order="popularity"),
    "popular": CatalogCollectionInfo(slug="popular", title="Популярные аниме", order="ranked"),
    **{slug: CatalogCollectionInfo(slug=slug, title=title, order="ranked")
       for slug, title, _ in THEMATIC_COLLECTIONS},
}
_collection_genres = {slug: genre_id for slug, _, genre_id in THEMATIC_COLLECTIONS}
_shiki_inflight: dict[tuple, asyncio.Task] = {}
_shiki_request_budgets = WeakKeyDictionary()


class _ShikiRequestBudget:
    """Below Shikimori's 5 req/s and 90 req/min, without a minute-long queue."""
    def __init__(self):
        self.lock = asyncio.Lock()
        self.starts = deque()

    async def admit(self):
        async with self.lock:
            now = monotonic()
            while self.starts and self.starts[0] <= now - 60:
                self.starts.popleft()
            if len(self.starts) >= 80:
                wait = max(1, int(60 - (now - self.starts[0])) + 1)
                raise HTTPException(503, "Каталог сейчас обновляется. Повторите запрос чуть позже.",
                                    headers={"Retry-After": str(wait)})
            delay = max(0, self.starts[-1] + 0.26 - now) if self.starts else 0
            if delay:
                await asyncio.sleep(delay)
            self.starts.append(monotonic())


async def _admit_shiki_request():
    loop = asyncio.get_running_loop()
    budget = _shiki_request_budgets.get(loop)
    if budget is None:
        budget = _ShikiRequestBudget()
        _shiki_request_budgets[loop] = budget
    await budget.admit()


async def shiki_request(path, params=None, *, json_body=None):
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.EXTERNAL_READ_TIMEOUT_SECONDS,
                                                    connect=settings.EXTERNAL_CONNECT_TIMEOUT_SECONDS),
                                 headers={"User-Agent": "Amergination/1.0"}) as client:
        try:
            async def fetch():
                await _admit_shiki_request()
                if json_body is None:
                    response = await client.get(SHIKI + "/api/" + path, params=params)
                else:
                    response = await client.post(SHIKI + "/api/" + path, json=json_body)
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


async def cached_shiki(path, params=None, ttl=21600, validator=None, *, json_body=None):
    key = "catalog:shiki:v1:" + path + ":" + str(sorted((params or {}).items()))
    if json_body is not None:
        key += ":post:" + hashlib.sha256(json.dumps(json_body, sort_keys=True).encode()).hexdigest()
    cached = await get_cached_json(key)
    if cached is not None:
        try:
            if validator:
                validator(cached)
            return cached
        except HTTPException:
            pass  # Rebuild malformed collection data instead of serving it for six hours.
    inflight_key = (asyncio.get_running_loop(), key)
    task = _shiki_inflight.get(inflight_key)
    if task is None:
        if len(_shiki_inflight) >= 32:
            raise HTTPException(503, "Каталог сейчас загружается. Попробуйте ещё раз.",
                                headers={"Retry-After": "2"})

        async def load():
            data = (await shiki_request(path, params, json_body=json_body) if json_body is not None
                    else await shiki_request(path, params))
            if validator:
                validator(data)
            await set_cached_json(key, ttl, data)
            return data

        task = asyncio.create_task(load())
        _shiki_inflight[inflight_key] = task

        def finished(completed):
            if _shiki_inflight.get(inflight_key) is completed:
                _shiki_inflight.pop(inflight_key, None)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)
    return await asyncio.shield(task)


def _poster_mapping(payload, ids):
    if (not isinstance(payload, dict) or payload.get("errors")
            or not isinstance(payload.get("data"), dict)
            or not isinstance(payload["data"].get("animes"), list)):
        raise HTTPException(502, "Некорректные метаданные постеров Shikimori")
    result = {}
    for item in payload["data"]["animes"]:
        if not isinstance(item, dict) or item.get("id") not in ids or item["id"] in result:
            raise HTTPException(502, "Некорректная привязка постера Shikimori")
        poster = item.get("poster")
        if poster is not None and not isinstance(poster, dict):
            raise HTTPException(502, "Некорректный постер Shikimori")
        result[item["id"]] = poster_url((poster or {}).get("mainUrl"), SHIKI)
    return result


async def apply_posters(cards):
    """Overlay current poster metadata in batches, including already cached cards.

    Legacy REST image fields can contain a successful JPEG depicting '404'.
    GraphQL poster URLs are authoritative; a poster outage must not hide titles.
    """
    targets = [card for card in cards if card.source == "shikimori"
               and re.fullmatch(r"[1-9][0-9]{0,19}", card.external_id)]
    ids = sorted({card.external_id for card in targets}, key=int)
    try:
        async with asyncio.timeout(min(5, settings.EXTERNAL_SERVICE_TIMEOUT_SECONDS)):
            for offset in range(0, len(ids), 50):
                batch = ids[offset:offset + 50]
                body = {"query": "query Posters($ids: String!) { animes(ids: $ids, limit: 50) { id poster { mainUrl } } }",
                        "variables": {"ids": ",".join(batch)}}
                payload = await cached_shiki("graphql", ttl=3600, json_body=body,
                                             validator=lambda data: _poster_mapping(data, batch))
                mapping = _poster_mapping(payload, batch)
                for card in targets:
                    if card.external_id in mapping:
                        value = mapping[card.external_id]
                        card.poster_url = AnyHttpUrl(value) if value else None
    except (HTTPException, TimeoutError):
        log.warning("Current Shikimori posters unavailable; keeping usable legacy images")
    for card in targets:
        value = poster_url(str(card.poster_url)) if card.poster_url else None
        card.poster_url = AnyHttpUrl(value) if value else None


def shiki_card(data):
    return AnimeCard(
        source="shikimori", external_id=str(data["id"]), title=data.get("russian") or data["name"],
        original_title=data.get("name"), page_url=SHIKI + data["url"],
        poster_url=poster_url((data.get("image") or {}).get("original"), SHIKI),
        year=number((data.get("aired_on") or "")[:4]), kind=KIND.get(data.get("kind"), data.get("kind")),
        status=data.get("status"), score=number(data.get("score"), float),
        genres=[genre.get("russian") or genre["name"] for genre in data.get("genres", [])],
    )


def _collection_cards(data):
    if not isinstance(data, list):
        raise HTTPException(502, "Shikimori вернул некорректный список аниме")
    cards, seen = [], set()
    try:
        for item in data:
            if not isinstance(item, dict) or not re.fullmatch(r"[1-9][0-9]{0,19}", str(item.get("id", ""))):
                raise ValueError
            external_id = str(item["id"])
            if external_id in seen:
                continue
            cards.append(shiki_card(item))
            seen.add(external_id)
            if len(cards) == COLLECTION_LIMIT:
                break
    except (KeyError, TypeError, ValueError, AttributeError):
        raise HTTPException(502, "Shikimori вернул некорректные карточки аниме") from None
    return cards


async def collection_catalog(slug, limit=COLLECTION_LIMIT):
    info = _collection_info.get(slug)
    if info is None:
        raise HTTPException(404, "Подборка не найдена")
    # Every UI limit shares one top-50 cache entry; there are no per-card details calls.
    # ranked selects the provider's top 50. Display that bounded set by score;
    # do not claim we scanned/ranked every title in the whole Shikimori catalog.
    params = {"status": "released", "kind": "tv,movie,ona", "order": info.order, "limit": COLLECTION_LIMIT}
    ttl = 21600
    if slug == "ongoing":
        params.update(status="ongoing", kind="tv,ona")
        ttl = 1800
    elif slug in _collection_genres:
        params["genre_v2"] = _collection_genres[slug]
        params["status"] = "released,ongoing"
        params["kind"] = "tv,movie,ova,ona,special,tv_special"
    try:
        data = await cached_shiki("animes", params, ttl=ttl, validator=_collection_cards)
        cards = _collection_cards(data)
        await apply_posters(cards)
        await remember_titles(cards)
        if info.order == "ranked":
            # sorted is stable, so equal scores keep the provider's rank order.
            cards.sort(key=lambda card: (card.score is None, -(card.score or 0)))
        return CatalogCollection(**info.model_dump(), items=cards[:limit])
    except HTTPException as error:
        if error.status_code == 404:
            raise HTTPException(502, "Подборка временно недоступна на Shikimori") from None
        raise


async def home_catalog(limit):
    # Only two initial list requests; thematic shelves load lazily via their endpoint.
    results = await asyncio.gather(collection_catalog("ongoing", limit), collection_catalog("popular", limit),
                                   return_exceptions=True)
    shelves, warnings = [], []
    for name, result in zip(("Онгоинги", "Популярные аниме"), results):
        if isinstance(result, Exception):
            warnings.append(name + ": источник временно недоступен")
            shelves.append([])
        else:
            shelves.append(result.items)
    return HomeCatalog(ongoing=shelves[0], popular=shelves[1], warnings=warnings,
                       collections=[_collection_info[slug] for slug, _, _ in THEMATIC_COLLECTIONS])


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
    await remember_titles([match])
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
    if slug and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise HTTPException(422, "Некорректный slug AnimeGo")
    card_data = await get_cached_json("catalog:animego:card:" + external_id)
    if card_data and card_data.get("slug"):
        # A saved-list title can produce a different readable slug. Prefer the
        # upstream slug already verified for this exact ID over the URL spelling.
        slug = card_data["slug"]
    registered = await get_title("animego", external_id)
    if registered and registered.upstream_slug:
        slug = registered.upstream_slug
        if card_data:
            card_data = {**card_data, "slug": slug}
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


async def remember_playback_identity(page):
    """Keep the server-verified cross-source match for provider metadata lookups."""
    playback = page.playback
    if (playback.status == "matched" and page.details.source == "shikimori"
            and playback.shikimori_id == page.details.external_id
            and re.fullmatch(r"[1-9][0-9]{0,19}", playback.animego_id or "")
            and re.fullmatch(r"[1-9][0-9]{0,19}", playback.shikimori_id or "")):
        await set_cached_json(f"catalog:playback-shikimori:v1:{playback.animego_id}", 21600,
                              {"shikimori_id": playback.shikimori_id})


async def catalog_page(source, external_id, slug=None):
    key = f"catalog:page:v1:{source}:{external_id}"
    cached = await get_cached_json(key)
    if cached is not None:
        page = CatalogPage.model_validate(cached)
        await apply_posters([page.details, *page.related])
        await remember_titles([page.details, *page.related])
        await remember_playback_identity(page)
        return page
    page = await (shiki_page(external_id) if source == "shikimori" else animego_page(external_id, slug))
    await apply_posters([page.details, *page.related])
    await remember_titles([page.details, *page.related])
    if page.details.episodes_total:
        await set_cached_json(f"catalog:progress-total:v1:{page.details.source}:{page.details.external_id}",
                              86400, page.details.episodes_total)
    if not page.warnings and page.playback.status != "unavailable":
        await set_cached_json(key, 21600 if page.playback.status == "matched" else 1800, page.model_dump(mode="json"))
    await remember_playback_identity(page)
    return page


async def legacy_anime_path(source, external_id, slug=None):
    """Resolve old links without loading players just to build an address."""
    from backend.services.anime_urls import anime_path

    if slug and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise HTTPException(422, "Некорректный slug AnimeGo")
    registered = await get_title(source, external_id)
    if registered:
        return registered.public_path
    if source == "shikimori":
        card = shiki_card(await cached_shiki("animes/" + external_id))
        await remember_titles([card])
        return card.public_path
    if slug:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise HTTPException(422, "Некорректный slug AnimeGo")
        return anime_path("animego", external_id, slug=slug)
    cached = await get_cached_json("catalog:page:v1:animego:" + external_id)
    if cached is not None:
        card = CatalogPage.model_validate(cached).details
        await remember_titles([card])
        return card.public_path
    card = await get_cached_json("catalog:animego:card:" + external_id)
    if card:
        card = AnimeCard.model_validate(card)
        await remember_titles([card])
        return card.public_path
    raise HTTPException(404, "Откройте тайтл через поиск: для AnimeGo нужен slug страницы")
