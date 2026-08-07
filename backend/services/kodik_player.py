
import json
from fastapi import HTTPException
from backend.core.redis import redis_client
from backend.core.config import settings

from anime_parsers_ru import KodikParserAsync

async def get_kodik_parser() -> KodikParserAsync:
    """Создает и возвращает экземпляр KodikParserAsync с токеном"""
    if not settings.KODIK_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="KODIK_TOKEN не настроен в .env файле"
        )
    return KodikParserAsync(
        token=settings.KODIK_TOKEN,
        use_lxml=True,
        use_cache=True  # Включаем внутренний кэш библиотеки
    )


async def get_player_info_cached(shikimori_id: str) -> dict:
    """
    Получает информацию о сериях и переводах для аниме по Shikimori ID
    Кэширует результат на 6 часов
    """
    cache_key = f"kodik:info:{shikimori_id}"

    # 1. Проверяем Redis
    cached_data = await redis_client.get(cache_key)
    if cached_data:
        return json.loads(cached_data)

    # 2. Создаем парсер
    parser = await get_kodik_parser()

    try:
        # 3. Получаем информацию о сериях и переводах
        info = await parser.get_info(shikimori_id, "shikimori")

        # 4. Кэшируем на 6 часов (21600 секунд)
        await redis_client.setex(cache_key, 21600, json.dumps(info))

        return info

    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Ошибка при получении информации о плеере: {str(e)}"
        )
    finally:
        await parser.close_async_session()


async def get_stream_url_cached(
        shikimori_id: str,
        episode: int,
        translation_id: str,
        quality: int = 720
) -> dict:
    """
    Получает ссылку на m3u8 плейлист для конкретной серии
    Кэширует результат на 2 часа (ссылки часто протухают)
    """
    cache_key = f"kodik:stream:{shikimori_id}:{episode}:{translation_id}:{quality}"

    # 1. Проверяем Redis
    cached_data = await redis_client.get(cache_key)
    if cached_data:
        return json.loads(cached_data)

    parser = await get_kodik_parser()

    try:
        # 3. Получаем ссылку на m3u8 плейлист
        m3u8_link = await parser.get_m3u8_playlist_link(
            id=shikimori_id,
            id_type="shikimori",
            seria_num=episode,
            translation_id=translation_id,
            quality=quality
        )

        result = {
            "stream_url": m3u8_link,
            "quality": quality,
            "type": "hls"
        }


        await redis_client.setex(cache_key, 7200, json.dumps(result))

        return result

    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Ошибка при получении ссылки на видео: {str(e)}"
        )
    finally:
        await parser.close_async_session()


async def get_available_translations(shikimori_id: str) -> list:
    """
    Получает список доступных переводов/озвучек для аниме
    """
    info = await get_player_info_cached(shikimori_id)
    return info.get("translations", [])


async def get_series_count(shikimori_id: str) -> int:
    """
    Получает количество серий для аниме
    """
    info = await get_player_info_cached(shikimori_id)
    return info.get("series_count", 0)