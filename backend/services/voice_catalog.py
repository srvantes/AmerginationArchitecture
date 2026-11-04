"""Whole-provider episode catalogues. Never probe individual episodes for availability."""
import asyncio
import hashlib
import re

from fastapi import HTTPException

from backend.core.cache import get_cached_json, set_cached_json
from backend.core.config import settings
from backend.services.animego_service import get_embedded_player, normalize_animego_id
from backend.services.player_catalogs import aniboom, cvh, kodik


_inflight: dict[tuple, asyncio.Task] = {}
CACHE_SECONDS = 1800


def _result(numbers, status="ready", message=None):
    if not isinstance(numbers, list) or len(numbers) > 50000 or any(type(n) is not int or n < 1 for n in numbers):
        raise HTTPException(502, "Плеер вернул некорректный список серий")
    numbers = sorted(set(numbers))
    # next_offset=null also stops the old paginated frontend after its next request.
    return {"episodes": numbers, "status": status, "message": message,
            "checked": len(numbers), "total": len(numbers), "next_offset": None}


async def _load(anime_id, translation_id, player, episode, cache_key, shikimori_id=None):
    try:
        async with asyncio.timeout(settings.EXTERNAL_SERVICE_TIMEOUT_SECONDS):
            voice = await get_embedded_player(anime_id, episode, translation_id, player)
            embed = voice.get("embed", "")
            if player == "aniboom":
                numbers = await aniboom.get_episode_numbers(embed, translation_id)
            elif player == "cvh":
                numbers = await cvh.get_episode_numbers(embed, voice.get("label", ""))
            elif player == "kodik":
                numbers = await kodik.get_episode_numbers(embed, voice.get("label", ""),
                                                          shikimori_id=shikimori_id)
            else:
                raise HTTPException(501, "Каталог плеера не поддерживается")
            result = _result(numbers)
            await set_cached_json(cache_key, CACHE_SECONDS, result)
            return result
    except HTTPException as error:
        if error.status_code == 501:
            return _result([], "unsupported", "Полный список серий этого плеера пока недоступен. "
                           "Можно смотреть выбранную серию или выбрать другой плеер.")
        raise
    except TimeoutError:
        raise HTTPException(504, "Плеер не ответил вовремя. Повторите загрузку списка серий.") from None


async def get_voice_episode_catalog(anime_id: str, translation_id: str, player: str, episode: int = 1):
    anime_id = normalize_animego_id(anime_id)
    shikimori_id = None
    if player == "kodik":
        # Never trust a client-supplied cross-provider ID or guess by the title.
        identity = await get_cached_json(f"catalog:playback-shikimori:v1:{anime_id}")
        if (isinstance(identity, dict) and isinstance(identity.get("shikimori_id"), str)
                and re.fullmatch(r"[1-9][0-9]{0,19}", identity["shikimori_id"])):
            shikimori_id = identity["shikimori_id"]
    cache_key = f"animego:voice_catalog:v2:{anime_id}:{player}:{translation_id}:{episode}"
    if player == "kodik":
        origin = hashlib.sha256(settings.KODIK_SITE_URL.encode()).hexdigest()[:16]
        cache_key += ":" + origin + ":" + (shikimori_id or "unknown")
    cached = await get_cached_json(cache_key)
    if isinstance(cached, dict) and cached.get("status") == "ready":
        try:
            return _result(cached.get("episodes"))
        except HTTPException:
            pass  # Rebuild malformed cache entries instead of serving a broken catalogue.

    key = (asyncio.get_running_loop(), cache_key)
    task = _inflight.get(key)
    if task is None:
        if len(_inflight) >= 8:
            raise HTTPException(503, "Списки серий сейчас загружаются. Попробуйте ещё раз.")
        task = asyncio.create_task(_load(anime_id, translation_id, player, episode, cache_key, shikimori_id))
        _inflight[key] = task

        def finished(completed):
            if _inflight.get(key) is completed:
                _inflight.pop(key, None)
            if not completed.cancelled():
                completed.exception()  # Retrieve errors even when all clients disconnected.

        task.add_done_callback(finished)
    return await asyncio.shield(task)
