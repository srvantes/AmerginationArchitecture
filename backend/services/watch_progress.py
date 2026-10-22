"""Use server catalog metadata for bounds without blocking writes on providers."""
import asyncio

from fastapi import HTTPException

from backend.core.cache import get_cached_json
from backend.database.sсhemas.watchlist import WatchlistOut


async def known_episode_total(source: str, external_id: str) -> int | None:
    page = await get_cached_json(f"catalog:page:v1:{source}:{external_id}")
    details = page.get("details", {}) if isinstance(page, dict) else {}
    if not isinstance(details, dict):
        details = {}
    total = details.get("episodes_total")
    if not (type(total) is int and total > 0):
        total = await get_cached_json(f"catalog:progress-total:v1:{source}:{external_id}")
    return total if type(total) is int and total > 0 else None


async def validate_progress(source: str, external_id: str, progress: int) -> None:
    total = await known_episode_total(source, external_id)
    if total is not None and progress > total:
        raise HTTPException(422, f"У этого аниме всего {total} серий. Укажите число от 0 до {total}.")


async def present_entry(entry) -> WatchlistOut:
    output = WatchlistOut.model_validate(entry)
    metadata = {}
    if not output.poster_url or (entry.anime_source == "animego" and not output.anime_slug):
        page = await get_cached_json(f"catalog:page:v1:{entry.anime_source}:{entry.anime_external_id}")
        if isinstance(page, dict) and isinstance(page.get("details"), dict):
            metadata = page["details"]
        if not metadata.get("poster_url") and entry.anime_source == "animego":
            card = await get_cached_json("catalog:animego:card:" + entry.anime_external_id)
            if isinstance(card, dict):
                metadata = card
        if not metadata.get("poster_url") and entry.anime_source == "shikimori":
            raw = await get_cached_json(f"catalog:shiki:v1:animes/{entry.anime_external_id}:[]")
            if isinstance(raw, dict) and isinstance(raw.get("image"), dict):
                image = raw["image"].get("original")
                if isinstance(image, str) and image.startswith("/"):
                    metadata = {"poster_url": "https://shikimori.io" + image}
    return output.model_copy(update={
        "episodes_total": await known_episode_total(entry.anime_source, entry.anime_external_id),
        "poster_url": output.poster_url or metadata.get("poster_url"),
        "anime_slug": output.anime_slug or metadata.get("slug"),
    })


async def present_entries(entries) -> list[WatchlistOut]:
    return list(await asyncio.gather(*(present_entry(entry) for entry in entries)))
