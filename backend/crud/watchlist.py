from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models.watchlist import WatchlistEntry
from backend.database.models.anime import Review
from backend.services.achievements import sync_achievements
from backend.database.sсhemas.watchlist import WatchlistCreate, WatchlistUpdate, WatchStatus


class CRUDWatchlist:
    async def summary(self, db: AsyncSession, user_id: UUID) -> dict:
        result = await db.execute(select(
            func.count(WatchlistEntry.id),
            func.coalesce(func.sum(case((WatchlistEntry.status == "completed", 1), else_=0)), 0),
            func.coalesce(func.sum(WatchlistEntry.episodes_watched), 0),
        ).where(WatchlistEntry.user_id == user_id))
        total, completed, episodes = result.one()
        reviews = await db.execute(select(func.count(Review.id)).where(Review.user_id == user_id))
        return {
            "total": total, "completed": completed, "episodes_watched": episodes,
            "reviews_written": reviews.scalar_one(),
            "watching": await self.list_entries(db, user_id, "watching", 6, 0),
        }

    async def list_entries(
        self, db: AsyncSession, user_id: UUID, status: WatchStatus | None, limit: int, offset: int,
        anime_source: str | None = None, anime_external_id: str | None = None,
    ) -> list[WatchlistEntry]:
        query = select(WatchlistEntry).where(WatchlistEntry.user_id == user_id)
        if status is not None:
            query = query.where(WatchlistEntry.status == status)
        if anime_source is not None:
            query = query.where(WatchlistEntry.anime_source == anime_source)
        if anime_external_id is not None:
            query = query.where(WatchlistEntry.anime_external_id == anime_external_id)
        result = await db.execute(
            query.order_by(WatchlistEntry.created_at.desc(), WatchlistEntry.id)
            .limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def create(self, db: AsyncSession, user_id: UUID, data: WatchlistCreate) -> WatchlistEntry:
        entry = WatchlistEntry(user_id=user_id, **data.model_dump())
        db.add(entry)
        await sync_achievements(db, user_id)
        await db.commit()
        await db.refresh(entry)
        return entry

    async def get_owned(self, db: AsyncSession, user_id: UUID, entry_id: UUID) -> WatchlistEntry | None:
        result = await db.execute(select(WatchlistEntry).where(
            WatchlistEntry.id == entry_id, WatchlistEntry.user_id == user_id,
        ))
        return result.scalar_one_or_none()

    async def update(
        self, db: AsyncSession, entry: WatchlistEntry, data: WatchlistUpdate,
    ) -> WatchlistEntry:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(entry, field, value)
        await sync_achievements(db, entry.user_id)
        await db.commit()
        await db.refresh(entry)
        return entry

    async def delete(self, db: AsyncSession, entry: WatchlistEntry) -> None:
        await db.delete(entry)
        await db.commit()


crud_watchlist = CRUDWatchlist()
