from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user, get_optional_user
from backend.crud.user import crud_user
from backend.crud.watchlist import crud_watchlist
from backend.database.models.user import User
from backend.services.watch_progress import present_entry, present_entries, validate_progress
from backend.database.sсhemas.anime import AnimeSource
from backend.database.sсhemas.watchlist import WatchlistCreate, WatchlistOut, WatchlistUpdate, WatchStatus, WatchlistSummary


router = APIRouter(tags=["users"])


@router.get("/me/watchlist/summary", response_model=WatchlistSummary)
async def get_my_watchlist_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await crud_watchlist.summary(db, user.id)


@router.get("/me/watchlist", response_model=list[WatchlistOut])
async def get_my_watchlist(
    status: WatchStatus | None = None,
    anime_source: AnimeSource | None = None,
    anime_external_id: str | None = Query(None, min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    entries = await crud_watchlist.list_entries(db, user.id, status, limit, offset, anime_source, anime_external_id)
    return await present_entries(entries)


@router.post("/me/watchlist", response_model=WatchlistOut, status_code=201)
async def add_to_watchlist(
    data: WatchlistCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if data.episodes_watched:
        await validate_progress(data.anime_source, data.anime_external_id, data.episodes_watched)
    try:
        entry = await crud_watchlist.create(db, user.id, data)
        return await present_entry(entry)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Anime already exists in your watchlist")


@router.patch("/me/watchlist/{entry_id}", response_model=WatchlistOut)
async def update_watchlist_entry(
    entry_id: UUID,
    data: WatchlistUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    entry = await crud_watchlist.get_owned(db, user.id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    if data.episodes_watched is not None:
        await validate_progress(entry.anime_source, entry.anime_external_id, data.episodes_watched)
    entry = await crud_watchlist.update(db, entry, data)
    return await present_entry(entry)


@router.delete("/me/watchlist/{entry_id}", status_code=204)
async def delete_watchlist_entry(
    entry_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    entry = await crud_watchlist.get_owned(db, user.id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    await crud_watchlist.delete(db, entry)
    return Response(status_code=204)


async def accessible_watchlist(user_id, user, db):
    profile = await crud_user.get_user_profile(db, user_id)
    if profile is None or not profile.is_active:
        raise HTTPException(status_code=404, detail="User not found")
    if not profile.show_watchlist and (user is None or user_id != user.id):
        raise HTTPException(status_code=403, detail="Этот список аниме скрыт владельцем.",
                            headers={"Cache-Control": "private, no-store"})


@router.get("/{user_id}/watchlist/summary", response_model=WatchlistSummary)
async def get_user_watchlist_summary(
    user_id: UUID,
    response: Response,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    await accessible_watchlist(user_id, user, db)
    return await crud_watchlist.summary(db, user_id)


@router.get("/{user_id}/watchlist", response_model=list[WatchlistOut])
async def get_user_watchlist(
    user_id: UUID,
    response: Response,
    status: WatchStatus | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    await accessible_watchlist(user_id, user, db)
    return await present_entries(await crud_watchlist.list_entries(db, user_id, status, limit, offset))
