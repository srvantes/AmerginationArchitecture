from typing import Literal

from fastapi import APIRouter, Query, HTTPException


from backend.services.shikimori_client import search_anime_cached, get_anime_details_cached
from backend.services.animego_service import (
    search_animego,
    get_voices_cached,
    get_stream_url,
    get_episodes_from_page,
    get_episodes_info
)
from backend.services.kodik_player import get_player_info_cached, get_stream_url_cached

router = APIRouter(tags=["anime"])

@router.get("/search")
async def search_anime(q:str = Query(..., min_length=2, description="Название произведения")):

    result = await search_anime_cached(q)
    return result

@router.get("/details",)
async def get_anime(shikimori_link: str = Query(..., description="Линк на аниме")):
    result = await get_anime_details_cached(shikimori_link)
    return result




### AnimeGo service


@router.get("/animego/search")
async def animego_search(q: str = Query(..., min_length=2, description="Название аниме")):
    """Поиск аниме на AnimeGO"""
    return await search_animego(q)


@router.get("/animego/episodes")
async def animego_episodes(
    anime_id: str = Query(..., description="slug-id аниме, например: naruto-uragannye-hroniki-103")
):
    """Список всех эпизодов (с fallback)"""
    try:
        return await get_episodes_info(anime_id)
    except HTTPException as e:
        # Если основной метод упал с 404 — пробуем альтернативный
        if "404" in str(e.detail) or "не найден" in str(e.detail):
            return await get_episodes_from_page(anime_id)
        raise


@router.get("/animego/voices")
async def animego_voices(
    anime_id: str = Query(..., description="ID аниме на AnimeGO"),
    episode: int = Query(1, ge=1, description="Номер эпизода")
):
    """Список доступных озвучек для конкретного эпизода"""
    return await get_voices_cached(anime_id, episode)


@router.get("/animego/stream")
async def animego_stream(
    anime_id: str = Query(..., description="ID аниме на AnimeGO"),
    episode: int = Query(..., ge=1, description="Номер эпизода"),
    translation_id: str = Query(..., description="ID озвучки"),
    player: str = Query("aniboom", description="Тип плеера (aniboom или cvh)")
):
    """Получение ссылки на видеопоток"""
    return await get_stream_url(anime_id, episode, translation_id, player)


@router.get("/kodik/info")
async def kodik_info(
    shikimori_id: str = Query(..., min_length=1, description="ID аниме на Shikimori"),
):
    """Получение доступных серий и переводов по ID Shikimori."""
    return await get_player_info_cached(shikimori_id)


@router.get("/kodik/stream")
async def kodik_stream(
    shikimori_id: str = Query(..., min_length=1, description="ID аниме на Shikimori"),
    episode: int = Query(..., ge=1, description="Номер эпизода"),
    translation_id: str = Query(..., min_length=1, description="ID перевода"),
    quality: Literal[360, 480, 720, 1080] = 720,
):
    """Получение HLS-ссылки для выбранной серии и перевода."""
    return await get_stream_url_cached(shikimori_id, episode, translation_id, quality)

