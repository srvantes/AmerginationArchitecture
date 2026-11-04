from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.database.models.user import User
from backend.database.sсhemas.playback_history import (
    PlaybackAnimeId, PlaybackHistoryOut, PlaybackHistoryWrite, PlaybackSource,
)
from backend.services.playback_history import get_history, list_history, save_history


router = APIRouter(tags=["playback history"])


@router.get("", response_model=list[PlaybackHistoryOut])
async def my_playback_history(
    limit: int = Query(12, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_history(db, user.id, limit, offset)


@router.get("/{anime_source}/{anime_external_id}", response_model=PlaybackHistoryOut)
async def my_anime_playback_history(
    anime_source: PlaybackSource,
    anime_external_id: PlaybackAnimeId,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    entry = await get_history(db, user.id, anime_source, anime_external_id)
    if entry is None:
        raise HTTPException(404, "История просмотра этого аниме пока пуста")
    return entry


@router.put("/{anime_source}/{anime_external_id}", response_model=PlaybackHistoryOut)
async def save_my_anime_playback_history(
    anime_source: PlaybackSource,
    anime_external_id: PlaybackAnimeId,
    data: PlaybackHistoryWrite,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await save_history(db, user.id, anime_source, anime_external_id, data)
