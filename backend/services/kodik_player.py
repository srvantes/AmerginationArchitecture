
import asyncio
from fastapi import HTTPException
from backend.core.cache import get_cached_json, set_cached_json
from backend.core.config import settings
from backend.services.upstream import run_async

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
    cached_data = await get_cached_json(cache_key)
    if cached_data is not None:
        return cached_data

    # 2. Создаем парсер
    parser = await get_kodik_parser()

    try:
        # 3. Получаем информацию о сериях и переводах
        info = await run_async(
            lambda: parser.get_info(shikimori_id, "shikimori"),
            provider="Kodik",
        )

        # 4. Кэшируем на 6 часов (21600 секунд)
        await set_cached_json(cache_key, 21600, info)

        return info

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Kodik не ответил вовремя")
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail="Информация о плеере Kodik временно недоступна"
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
    cached_data = await get_cached_json(cache_key)
    if cached_data is not None:
        return cached_data

    parser = await get_kodik_parser()

    try:
        # 3. Получаем ссылку на m3u8 плейлист
        m3u8_link = await run_async(
            lambda: parser.get_m3u8_playlist_link(
                id=shikimori_id,
                id_type="shikimori",
                seria_num=episode,
                translation_id=translation_id,
                quality=quality,
            ),
            provider="Kodik",
        )

        result = {
            "stream_url": m3u8_link,
            "quality": quality,
            "type": "hls"
        }


        await set_cached_json(cache_key, 7200, result)

        return result

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Kodik не ответил вовремя")
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail="Видеопоток Kodik временно недоступен"
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
