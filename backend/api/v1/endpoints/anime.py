from typing import Literal

from fastapi import APIRouter, Depends, Query, HTTPException, Path
from backend.core.rate_limit import limited_catalog_read, RATE_LIMIT_RESPONSES


from backend.services.shikimori_client import search_anime_cached, get_anime_details_cached
from backend.services.animego_service import (
    search_animego,
    get_voices_cached,
    get_stream_url,
    get_episodes_from_page,
    get_episodes_info
)
from backend.services.animego_service import normalize_animego_id, get_embedded_player
from backend.services.voice_catalog import get_voice_episode_catalog
from backend.services.kodik_player import get_player_info_cached, get_stream_url_cached
from backend.database.sсhemas.catalog import AnimeCard, AnimeDetails, EpisodeList, PlayerInfo, StreamInfo, StreamQuality
from backend.services.catalog_adapters import anime_card, anime_details, episode_list, player_info, stream_info
from backend.database.sсhemas.catalog import EmbeddedPlayer, VoiceEpisodeCatalog
from backend.services.catalog_adapters import embedded_player

from backend.database.sсhemas.catalog import HomeCatalog, CatalogPage, CatalogCollection
from backend.services.catalog_service import home_catalog, catalog_page, collection_catalog, apply_posters
from backend.services.anime_registry import remember_titles
from backend.services import direct_kodik

router = APIRouter(tags=["anime"], dependencies=[Depends(limited_catalog_read)], responses=RATE_LIMIT_RESPONSES)


@router.get("/catalog/home", response_model=HomeCatalog)
async def live_home(limit: int = Query(12, ge=1, le=30)):
    return await home_catalog(limit)


@router.get("/catalog/collections/{slug}", response_model=CatalogCollection,
            responses={404: {"description": "Подборка не найдена"},
                       502: {"description": "Источник подборки временно недоступен"},
                       504: {"description": "Источник не ответил вовремя"}})
async def live_collection(slug: str, limit: int = Query(50, ge=1, le=50)):
    return await collection_catalog(slug, limit)


@router.get("/catalog/{source}/{external_id}", response_model=CatalogPage)
async def live_page(source: Literal["shikimori", "animego"], external_id: str = Path(pattern=r"^[1-9][0-9]*$"), slug: str | None = Query(None, max_length=300), defer_playback: bool = False):
    return await catalog_page(source, external_id, slug, defer_playback=defer_playback)

@router.get("/search", response_model=list[AnimeCard])
async def search_anime(q:str = Query(..., min_length=2, description="Название произведения")):

    result = await search_anime_cached(q)
    cards = [anime_card(item, "shikimori") for item in result]
    await apply_posters(cards)
    await remember_titles(cards)
    return cards

@router.get("/details", response_model=AnimeDetails)
async def get_anime(shikimori_link: str = Query(..., description="Линк на аниме")):
    result = await get_anime_details_cached(shikimori_link)
    details = anime_details(result, shikimori_link)
    await apply_posters([details])
    await remember_titles([details])
    return details




### AnimeGo service


@router.get("/animego/search", response_model=list[AnimeCard])
async def animego_search(q: str = Query(..., min_length=2, description="Название аниме")):
    """Поиск аниме на AnimeGO"""
    cards = [anime_card(item, "animego") for item in await search_animego(q)]
    await remember_titles(cards)
    return cards


@router.get("/animego/episodes", response_model=EpisodeList, responses={
    404: {"description": "Аниме или список серий не найден"},
    502: {"description": "Ошибка ответа AnimeGo"},
    504: {"description": "AnimeGo не ответил вовремя"},
})
async def animego_episodes(
    anime_id: str = Query(..., description="Числовой ID AnimeGo (например, 3127) или полный slug страницы")
):
    """Список всех эпизодов (с fallback)"""
    anime_id = normalize_animego_id(anime_id)
    try:
        result = await get_episodes_info(anime_id)
    except HTTPException as e:
        # Если основной метод упал с 404 — пробуем альтернативный
        if e.status_code != 404:
            raise
        result = None
    if not result:
        result = await get_episodes_from_page(anime_id)
    return episode_list(result, anime_id)


@router.get("/animego/voices", response_model=PlayerInfo)
async def animego_voices(
    anime_id: str = Query(..., description="ID аниме на AnimeGO"),
    episode: int = Query(1, ge=1, description="Номер эпизода")
):
    """Список доступных озвучек для конкретного эпизода"""
    anime_id = normalize_animego_id(anime_id)
    return player_info(await get_voices_cached(anime_id, episode), "animego", anime_id)


@router.get("/animego/voice-episodes", response_model=VoiceEpisodeCatalog)
async def animego_voice_episodes(
    anime_id: str = Query(..., min_length=1),
    translation_id: str = Query(..., min_length=1, max_length=100),
    player: Literal["kodik", "sibnet", "aniboom", "cvh"] = Query(...),
    episode: int = Query(1, ge=1),
):
    return await get_voice_episode_catalog(anime_id, translation_id, player, episode)


@router.get("/animego/stream", response_model=StreamInfo)
async def animego_stream(
    anime_id: str = Query(..., description="ID аниме на AnimeGO"),
    episode: int = Query(..., ge=1, description="Номер эпизода"),
    translation_id: str = Query(..., description="ID озвучки"),
    player: Literal["aniboom", "cvh"] = Query("aniboom", description="Тип плеера (aniboom или cvh)")
):
    """Получение ссылки на видеопоток"""
    anime_id = normalize_animego_id(anime_id)
    result = await get_stream_url(anime_id, episode, translation_id, player)
    return stream_info(result, "animego", anime_id, episode, translation_id)


@router.get("/animego/player", response_model=EmbeddedPlayer)
async def animego_player(
    anime_id: str = Query(..., min_length=1),
    episode: int = Query(1, ge=1),
    translation_id: str = Query(..., min_length=1),
    player: Literal["kodik", "sibnet", "aniboom", "cvh"] = "kodik",
):
    """Встроенный плеер выбранной озвучки; Kodik здесь не требует API-токена."""
    anime_id = normalize_animego_id(anime_id)
    voice = await get_embedded_player(anime_id, episode, translation_id, player)
    return embedded_player(voice, anime_id, episode)


@router.get("/kodik/info", response_model=PlayerInfo)
async def kodik_info(
    shikimori_id: str = Query(..., min_length=1, description="ID аниме на Shikimori"),
):
    """Получение доступных серий и переводов по ID Shikimori."""
    return player_info(await get_player_info_cached(shikimori_id), "kodik", shikimori_id)


@router.get("/kodik/catalog", response_model=PlayerInfo)
async def direct_kodik_catalog(shikimori_id: str = Query(pattern=r"^[1-9][0-9]{0,19}$")):
    title = await direct_kodik.get_title(shikimori_id)
    return PlayerInfo(source="kodik", external_id=shikimori_id, id_source="shikimori",
                      translations=[{**voice.model_dump(), "player": "kodik", "source": "kodik"}
                                    for voice in title.translations], episodes=title.episodes)


@router.get("/kodik/voice-episodes", response_model=VoiceEpisodeCatalog)
async def direct_kodik_episodes(shikimori_id: str = Query(pattern=r"^[1-9][0-9]{0,19}$"),
                               translation_id: str = Query(pattern=r"^[1-9][0-9]{0,19}$")):
    voice = await direct_kodik.get_voice(shikimori_id, translation_id)
    numbers = sorted(voice.episodes)
    return VoiceEpisodeCatalog(episodes=numbers, checked=len(numbers), total=len(numbers))


@router.get("/kodik/player", response_model=EmbeddedPlayer)
async def direct_kodik_player(shikimori_id: str = Query(pattern=r"^[1-9][0-9]{0,19}$"),
                             translation_id: str = Query(pattern=r"^[1-9][0-9]{0,19}$"),
                             episode: int = Query(ge=1, le=100000)):
    voice = await direct_kodik.get_voice(shikimori_id, translation_id)
    embed = voice.episodes.get(episode)
    if embed is None:
        raise HTTPException(404, "Серия недоступна в выбранной озвучке Kodik")
    return EmbeddedPlayer(source="kodik", external_id=shikimori_id, episode=episode,
                          translation_id=voice.translation.id, translation_name=voice.translation.name,
                          player="kodik", embed_url=embed)


@router.get("/kodik/stream", response_model=StreamInfo)
async def kodik_stream(
    shikimori_id: str = Query(..., min_length=1, description="ID аниме на Shikimori"),
    episode: int = Query(..., ge=0, description="Номер эпизода; 0 для фильма"),
    translation_id: str = Query(..., min_length=1, description="ID перевода"),
    quality: StreamQuality = StreamQuality.Q720,
):
    """Получение HLS-ссылки для выбранной серии и перевода."""
    result = await get_stream_url_cached(shikimori_id, episode, translation_id, quality.value)
    return stream_info(result, "kodik", shikimori_id, episode, translation_id)

