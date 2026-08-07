import json
from fastapi import HTTPException
import shikimori_api
from anime_parsers_ru import parser_shikimori_async, ShikimoriParserAsync

from backend.core.redis import redis_client

async def search_anime_cashed(query: str, limit: int = 10):
    cache_key = f"shiki:search:{query.lower().strip()}"


    cached_data = await redis_client.get(cache_key)
    if cached_data:
        return json.loads(cached_data)

    pareser = ShikimoriParserAsync(use_lxml=True)

    try:


        results = await pareser.search(title=query.lower().strip())

        await redis_client.setex(cache_key, 86400, json.dumps(results))

        return results

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка при попытке обратится к Shikimori: {e}")

    finally:
        await pareser.close_async_session()


async def get_anime_details_cached(shikimori_link: str) -> dict:
    cached_key = f"shiki:details:{_extract_id_from_link(shikimori_link)}"

    cached_data = await redis_client.get(cached_key)
    if cached_data:
        return json.loads(cached_data)

    parser = ShikimoriParserAsync(use_lxml=True)

    try:
        results = await parser.anime_info(shikimori_link)

        await redis_client.setex(cached_key, 2592000, json.dumps(results))
        return results


    except Exception as e:
        raise HTTPException(status_code=502, detail= f"Ошибка получения деталей об аниме: {e}")

    finally:

        await parser.close_async_session()


def _extract_id_from_link(shikimori_link: str) -> str:
    """Извлекает ID из ссылки Shikimori для использования в ключе кэша"""
    # "https://shikimori.one/animes/20-naruto" -> "20"
    # "https://shikimori.one/animes/z20-naruto" -> "20"
    try:
        path_part = shikimori_link.split("/animes/")[1]
        id_part = path_part.split("-")[0]
        # Убираем буквы (shikimori иногда добавляет 'z' перед ID)
        return ''.join(char for char in id_part if char.isdigit())
    except:
        # Если что-то пошло не так, используем всю ссылку как ключ
        return shikimori_link