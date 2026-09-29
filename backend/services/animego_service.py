import asyncio
import requests
from fastapi import HTTPException
from backend.core.cache import get_cached_json, set_cached_json
from backend.core.config import settings

from anime_parsers_ru import AnimegoParser



_parser = AnimegoParser(use_lxml=True, use_cache=True)


async def _run_sync(func, *args, **kwargs):
    """Запускает синхронную функцию в отдельном потоке, чтобы не блокировать event loop"""
    return await asyncio.wait_for(
        asyncio.to_thread(func, *args, **kwargs),
        timeout=settings.EXTERNAL_SERVICE_TIMEOUT_SECONDS,
    )


async def search_animego(query: str) -> list:
    """Поиск аниме на AnimeGO"""
    cache_key = f"animego:search:{query.lower().strip()}"

    cached = await get_cached_json(cache_key)
    if cached is not None:
        return cached

    try:
        results = await _run_sync(_parser.search, query)
        await set_cached_json(cache_key, 86400, results)  # 24 часа
        return results
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="AnimeGo не ответил вовремя")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка поиска на AnimeGO: {str(e)}")


async def get_voices_cached(anime_id: str, episode: int = 1) -> dict:
    """
    Получает список доступных озвучек и количество эпизодов.
    Кэширует на 6 часов.
    """
    cache_key = f"animego:voices:{anime_id}:{episode}"

    cached = await get_cached_json(cache_key)
    if cached is not None:
        return cached

    try:
        voices_data = await _run_sync(_parser.get_voices, anime_id, episode)
        await set_cached_json(cache_key, 21600, voices_data)  # 6 часов
        return voices_data
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="AnimeGo не ответил вовремя")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка получения озвучек: {str(e)}")


async def get_stream_url(anime_id: str, episode: int, translation_id: str, player: str) -> dict:
    """
    Получает ссылку на видеопоток для конкретной озвучки.
    player: 'aniboom' или 'cvh'
    Кэширует на 2 часа (ссылки быстро протухают).
    """
    cache_key = f"animego:stream:{anime_id}:{episode}:{translation_id}:{player}"

    cached = await get_cached_json(cache_key)
    if cached is not None:
        return cached

    try:
        # Сначала получаем список озвучек, чтобы найти нужную
        voices_data = await get_voices_cached(anime_id, episode)

        target_voice = None
        for v in voices_data.get("voices", []):
            if v["translation_id"] == translation_id:
                target_voice = v
                break

        if not target_voice:
            raise HTTPException(status_code=404, detail=f"Озвучка {translation_id} не найдена")

        player_type = target_voice.get("player", "").lower()

        # === ANIBOOM ===
        if player_type == "aniboom":
            stream_data = await _run_sync(
                _parser.aniboom_get_stream_for_voice,
                translation_id=translation_id,
                episode=episode,
                anime_id=anime_id
            )

            result = {
                "url": stream_data.get("url"),
                "kind": stream_data.get("kind"),  # "MPD" или "HLS"
                "player": "aniboom",
                "translation": target_voice.get("label")
            }

        # === CVH ===
        elif player_type == "cvh":
            cvh_id = target_voice.get("cvh_id")
            if not cvh_id:
                raise HTTPException(status_code=500, detail="CVH ID не найден для этой озвучки")

            stream_data = await _run_sync(
                _parser.cvh_get_stream,
                cvh_id=cvh_id,
                season=1,  # Обычно 1 сезон, можно улучшить позже
                episode=episode,
                translation=target_voice.get("label")
            )

            # CVH возвращает HLS, DASH и MP4 — отдаем всё
            result = {
                "hls": stream_data.get("HLS"),
                "dash": stream_data.get("DASH"),
                "mp4": stream_data.get("MP4s", []),
                "player": "cvh",
                "translation": target_voice.get("label")
            }

        else:
            raise HTTPException(status_code=501, detail=f"Плеер {player_type} пока не поддерживается")

        await set_cached_json(cache_key, 7200, result)  # 2 часа
        return result

    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="AnimeGo не ответил вовремя")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка получения потока: {str(e)}")


async def get_episodes_info(anime_id: str) -> list:
    """Получает список всех эпизодов для аниме"""
    cache_key = f"animego:episodes:{anime_id}"

    cached = await get_cached_json(cache_key)
    if cached is not None:
        return cached

    try:
        episodes = await _run_sync(_parser.get_episodes_info, anime_id)
        await set_cached_json(cache_key, 43200, episodes)  # 12 часов
        return episodes
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="AnimeGo не ответил вовремя")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка получения эпизодов: {str(e)}")


async def get_episodes_from_page(anime_slug_id: str) -> list:
    """
    Альтернативный способ: парсим эпизоды прямо со страницы аниме.
    Работает когда /schedule/load не отвечает.
    """
    cache_key = f"animego:episodes_page:{anime_slug_id}"

    cached = await get_cached_json(cache_key)
    if cached is not None:
        return cached

    try:
        url = f"https://animego.org/anime/{anime_slug_id}"

        def _parse():
            from bs4 import BeautifulSoup

            resp = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }, timeout=15)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # Ищем список эпизодов в блоке плеера
            episodes = []
            episode_buttons = soup.find_all(attrs={"data-episode-number": True})

            for btn in episode_buttons:
                try:
                    num = int(btn.get("data-episode-number"))
                    # Пытаемся достать название
                    title_div = btn.find("div", class_="episode-title")
                    title = title_div.text.strip() if title_div else f"Серия {num}"
                    episodes.append({
                        "seria": num,
                        "title": title,
                        "air_date": None,
                        "is_released": True
                    })
                except (TypeError, ValueError):
                    continue

            return sorted(episodes, key=lambda x: x["seria"])

        episodes = await _run_sync(_parse)

        if not episodes:
            # Генерируем список 1..N на основе get_voices
            voices_data = await get_voices_cached(anime_slug_id, 1)
            total = voices_data.get("total_episodes") or 12
            episodes = [{"seria": i, "title": f"Серия {i}", "air_date": None, "is_released": True}
                        for i in range(1, total + 1)]

        await set_cached_json(cache_key, 43200, episodes)
        return episodes

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="AnimeGo не ответил вовремя")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка парсинга эпизодов: {str(e)}")
