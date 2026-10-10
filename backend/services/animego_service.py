import asyncio
import json
import logging
import time
from functools import partial
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
import re
import unicodedata
import requests
from fastapi import HTTPException
from backend.core.cache import get_cached_json, set_cached_json
from backend.core.config import settings

from anime_parsers_ru import AnimegoParser, errors, parser_animego
from backend.services.upstream import ParserRequests, get_sync, run_sync_operation



log = logging.getLogger(__name__)
# Scope the transport adapter to AnimeGo; don't change requests globally.
parser_animego.requests = ParserRequests()
_parser_workers = ThreadPoolExecutor(max_workers=8, thread_name_prefix="animego")
_parser = AnimegoParser(use_lxml=True, use_cache=True)


def normalize_animego_id(value: str) -> str:
    """Accept a numeric ID or a page slug; the parser needs the final numeric ID."""
    match = re.fullmatch(r"(?:[a-z0-9]+(?:-[a-z0-9]+)*-)?([1-9][0-9]*)", value.strip(), re.IGNORECASE)
    if match is None:
        raise HTTPException(status_code=422, detail="AnimeGo ID должен быть числом или slug с числовым ID")
    return match.group(1)


async def _run_sync(func, *args, **kwargs):
    """Запускает синхронную функцию в отдельном потоке, чтобы не блокировать event loop"""
    return await asyncio.wait_for(
        asyncio.get_running_loop().run_in_executor(
            _parser_workers, run_sync_operation, partial(func, *args, **kwargs),
            time.monotonic() + settings.EXTERNAL_SERVICE_TIMEOUT_SECONDS),
        timeout=settings.EXTERNAL_SERVICE_TIMEOUT_SECONDS,
    )


def _search_words(value: str) -> list[str]:
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return re.findall(r"[^\W_]+", value, re.UNICODE)


def _relevant_search_results(results: list, words: list[str]) -> list:
    """Match all query words within one title; preserve provider order for ties."""
    phrase = " ".join(words)
    ranked = []
    for item in results:
        ranks = []
        for field in ("title", "original_title", "slug"):
            title_words = _search_words(item.get(field) or "")
            if not all(any(word.startswith(term) for word in title_words) for term in words):
                continue
            title = " ".join(title_words)
            rank = 0 if title == phrase else 1 if title.startswith(phrase + " ") else 2
            ranks.append(rank)
        if ranks:
            ranked.append((min(ranks), item))
    return [item for _, item in sorted(ranked, key=lambda entry: entry[0])]


async def search_animego(query: str) -> list:
    """Поиск аниме на AnimeGO"""
    words = _search_words(query)
    if len("".join(words)) < 2:
        raise HTTPException(status_code=422, detail="Введите хотя бы два символа названия")
    query = " ".join(words)
    cache_key = f"animego:search:v2:{query}"

    cached = await get_cached_json(cache_key)
    if cached is not None:
        return cached

    try:
        results = await _run_sync(_parser.search, query)
        results = _relevant_search_results(results, words)
        await set_cached_json(cache_key, 86400, results)  # 24 часа
        return results
    except (asyncio.TimeoutError, requests.Timeout):
        raise HTTPException(status_code=504, detail="AnimeGo не ответил вовремя")
    except errors.NoResults:
        return []
    except Exception as e:
        log.warning("AnimeGo request failed (%s)", type(e).__name__)
        raise HTTPException(status_code=502, detail="Поиск AnimeGo временно недоступен")


async def get_voices_cached(anime_id: str, episode: int = 1) -> dict:
    """
    Получает список доступных озвучек и количество эпизодов.
    Кэширует на 6 часов.
    """
    anime_id = normalize_animego_id(anime_id)
    cache_key = f"animego:voices:v2:{anime_id}:{episode}"

    try:
        episodes = await get_episodes_from_page(anime_id)
        selected = next((item for item in episodes if item["seria"] == episode), None)
        if episodes and selected is None:
            raise HTTPException(status_code=404, detail="Серия не найдена на AnimeGo")
        if selected and selected.get("video_id"):
            # anime-parsers-ru 1.18 otherwise searches only the first 100 episodes.
            _parser._player_url_cache[f"{anime_id}_ep_{episode}"] = (
                f"{_parser._ANIMEGO_BASE}/player/videos/{selected['video_id']}"
            )
        cached = await get_cached_json(cache_key)
        if cached is not None:
            return cached
        voices_data = await _run_sync(_parser.get_voices, anime_id, episode)
        if episodes:
            voices_data["total_episodes"] = max(item["seria"] for item in episodes)
        await set_cached_json(cache_key, 21600, voices_data)  # 6 часов
        return voices_data
    except (asyncio.TimeoutError, requests.Timeout):
        raise HTTPException(status_code=504, detail="AnimeGo не ответил вовремя")
    except HTTPException:
        raise
    except errors.NoResults:
        raise HTTPException(status_code=404, detail="Озвучки не найдены")
    except Exception as e:
        log.warning("AnimeGo request failed (%s)", type(e).__name__)
        raise HTTPException(status_code=502, detail="Озвучки AnimeGo временно недоступны")


async def get_stream_url(anime_id: str, episode: int, translation_id: str, player: str) -> dict:
    """
    Получает ссылку на видеопоток для конкретной озвучки.
    player: 'aniboom' или 'cvh'
    Кэширует на 2 часа (ссылки быстро протухают).
    """
    anime_id = normalize_animego_id(anime_id)
    cache_key = f"animego:stream:v2:{anime_id}:{episode}:{translation_id}:{player}"

    cached = await get_cached_json(cache_key)
    if cached is not None:
        return cached

    try:
        # Сначала получаем список озвучек, чтобы найти нужную
        voices_data = await get_voices_cached(anime_id, episode)

        target_voice = None
        for v in voices_data.get("voices", []):
            if str(v["translation_id"]) == translation_id and v.get("player", "").lower() == player.lower():
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
    except (asyncio.TimeoutError, requests.Timeout):
        raise HTTPException(status_code=504, detail="AnimeGo не ответил вовремя")
    except errors.NoResults:
        raise HTTPException(status_code=404, detail="Видеопоток не найден")
    except Exception as e:
        log.warning("AnimeGo request failed (%s)", type(e).__name__)
        raise HTTPException(status_code=502, detail="Видеопоток временно недоступен")


async def get_embedded_player(anime_id: str, episode: int, translation_id: str, player: str) -> dict:
    """Select both provider and translation: their IDs may repeat across players."""
    anime_id = normalize_animego_id(anime_id)
    voices = await get_voices_cached(anime_id, episode)
    for voice in voices.get("voices", []):
        if str(voice.get("translation_id")) == translation_id and str(voice.get("player", "")).lower() == player:
            return voice
    raise HTTPException(status_code=404, detail="Озвучка для выбранного плеера и серии не найдена")


async def get_episodes_info(anime_id: str) -> list:
    """Получает список всех эпизодов для аниме"""
    anime_id = normalize_animego_id(anime_id)
    cache_key = f"animego:episodes:v2:{anime_id}"

    cached = await get_cached_json(cache_key)
    if cached is not None:
        return cached

    try:
        episodes = await _run_sync(_parser.get_episodes_info, anime_id)
        if episodes:
            schedule = {int(item["seria"]): item for item in episodes}
            for item in await get_episodes_from_page(anime_id):
                number = item["seria"]
                schedule[number] = {**item, **schedule.get(number, {}), "is_released": True}
            episodes = [schedule[number] for number in sorted(schedule)]
        await set_cached_json(cache_key, 43200, episodes)  # 12 часов
        return episodes
    except (asyncio.TimeoutError, requests.Timeout):
        raise HTTPException(status_code=504, detail="AnimeGo не ответил вовремя")
    except errors.NoResults:
        raise HTTPException(status_code=404, detail="Эпизоды не найдены")
    except HTTPException:
        raise
    except errors.ServiceError as e:
        # Version 1.18 exposes HTTP status only in its exception message.
        if re.search(r"получен:\s*404\b", str(e), re.IGNORECASE):
            raise HTTPException(status_code=404, detail="Аниме или расписание не найдено на AnimeGo")
        raise HTTPException(status_code=502, detail="Список серий AnimeGo временно недоступен")
    except Exception as e:
        log.warning("AnimeGo request failed (%s)", type(e).__name__)
        raise HTTPException(status_code=502, detail="Список серий AnimeGo временно недоступен")


def _load_player_episodes(anime_id: str) -> list:
    """Read every advertised episode page, keeping internal IDs for playback."""
    from bs4 import BeautifulSoup

    def fetch(path, **params):
        response = get_sync(
            f"{_parser._ANIMEGO_BASE}{path}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                     "X-Requested-With": "XMLHttpRequest"},
            params=params or None,
        )
        response.raise_for_status()
        content = response.json()["data"]["content"]
        return BeautifulSoup(content, "html.parser")

    first = fetch(f"/player/{anime_id}")
    root = first.find(attrs={"data-anime-player-episodes-pages-value": True})
    pages, total = [], None
    if root:
        pages = json.loads(root["data-anime-player-episodes-pages-value"])
        total = int(root["data-anime-player-episodes-total-value"])
        if not isinstance(pages, list) or len(pages) > 100 or total < 0:
            raise ValueError("Некорректная пагинация серий AnimeGo")

    # Build the path from our validated numeric ID, not an upstream URL.
    page_numbers = sorted({int(page["page"]) for page in pages})
    if any(page < 0 or page >= 100 for page in page_numbers):
        raise ValueError("Некорректный номер страницы серий AnimeGo")
    context = copy_context()
    with ThreadPoolExecutor(max_workers=4) as pool:
        soups = [first, *pool.map(
            lambda page: context.copy().run(fetch, f"/player/{anime_id}/episodes", page=page),
            [page for page in page_numbers if page != 0],
        )]
    episodes = {}
    for soup in soups:
        for button in soup.find_all(attrs={"data-episode-number": True}):
            try:
                number = int(button["data-episode-number"])
            except (TypeError, ValueError):
                continue
            if number < 1:
                continue
            title = button.find("div", class_="episode-title")
            video_id = button.get("data-episode")
            episodes[number] = {
                "seria": number, "title": title.get_text(strip=True) if title else f"Серия {number}",
                "air_date": None, "is_released": True,
                "video_id": video_id if video_id and video_id.isdigit() else None,
            }
    if total is not None and len(episodes) != total:
        raise ValueError("AnimeGo вернул неполный список серий")
    return [episodes[number] for number in sorted(episodes)]


async def get_episodes_from_page(anime_slug_id: str) -> list:
    """Load all player episode pages; never cache a partial list."""
    anime_id = normalize_animego_id(anime_slug_id)
    cache_key = f"animego:episodes_page:v4:{anime_id}"
    cached = await get_cached_json(cache_key)
    if cached is not None:
        return cached
    try:
        episodes = await _run_sync(_load_player_episodes, anime_id)
        await set_cached_json(cache_key, 43200, episodes)
        return episodes
    except (asyncio.TimeoutError, requests.Timeout):
        raise HTTPException(status_code=504, detail="AnimeGo не ответил вовремя")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Аниме не найдено на AnimeGo")
        raise HTTPException(status_code=502, detail="Ошибка получения списка серий из плеера AnimeGo")
    except Exception as e:
        log.warning("AnimeGo request failed (%s)", type(e).__name__)
        raise HTTPException(status_code=502, detail="Список серий AnimeGo временно недоступен")
