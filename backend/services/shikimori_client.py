import asyncio
from urllib.parse import urlparse

from fastapi import HTTPException
from anime_parsers_ru import ShikimoriParserAsync

from backend.core.cache import get_cached_json, set_cached_json
from backend.core.config import settings
from backend.services.upstream import run_async


async def search_anime_cached(query: str, limit: int = 10):
    cache_key = f"shiki:search:{query.lower().strip()}"

    cached_data = await get_cached_json(cache_key)
    if cached_data is not None:
        return cached_data[:limit]

    parser = ShikimoriParserAsync(use_lxml=True)

    try:
        results = await run_async(
            lambda: parser.search(title=query.lower().strip()),
            provider="Shikimori",
        )
        await set_cached_json(cache_key, 86400, results)
        return results[:limit]

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Shikimori не ответил вовремя")
    except Exception as e:
        raise HTTPException(status_code=502, detail="Поиск Shikimori временно недоступен")

    finally:
        await parser.close_async_session()


async def get_anime_details_cached(shikimori_link: str) -> dict:
    _validate_shikimori_link(shikimori_link)
    cached_key = f"shiki:details:{_extract_id_from_link(shikimori_link)}"

    cached_data = await get_cached_json(cached_key)
    if cached_data is not None:
        return cached_data

    parser = ShikimoriParserAsync(use_lxml=True)

    try:
        results = await run_async(
            lambda: parser.anime_info(shikimori_link),
            provider="Shikimori",
        )

        await set_cached_json(cached_key, 2592000, results)
        return results


    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Shikimori не ответил вовремя")
    except Exception as e:
        raise HTTPException(status_code=502, detail= "Описание Shikimori временно недоступно")

    finally:

        await parser.close_async_session()


def _extract_id_from_link(shikimori_link: str) -> str:
    """Извлекает ID из ссылки Shikimori для использования в ключе кэша"""
    # "https://shikimori.one/animes/20-naruto" -> "20"
    # "https://shikimori.one/animes/z20-naruto" -> "20"
    path_part = shikimori_link.split("/animes/")[1]
    id_part = path_part.split("-")[0]
    return ''.join(char for char in id_part if char.isdigit())


def _validate_shikimori_link(shikimori_link: str) -> None:
    parsed = urlparse(shikimori_link)
    valid_hosts = {"shikimori.one", "www.shikimori.one", "shikimori.io", "www.shikimori.io"}
    anime_id = _extract_id_from_link(shikimori_link) if "/animes/" in parsed.path else ""
    if parsed.scheme != "https" or parsed.hostname not in valid_hosts or not anime_id:
        raise HTTPException(status_code=422, detail="Некорректная ссылка Shikimori")
