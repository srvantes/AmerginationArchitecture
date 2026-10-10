from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models.watchlist import WatchlistEntry
from backend.database.sсhemas.watchlist import WatchlistCreate, WatchlistUpdate, WatchStatus


class CRUDWatchlist:
    async def list_entries(
        self, db: AsyncSession, user_id: UUID, status: WatchStatus | None, limit: int, offset: int,
    ) -> list[WatchlistEntry]:
        query = select(WatchlistEntry).where(WatchlistEntry.user_id == user_id)
        if status is not None:
            query = query.where(WatchlistEntry.status == status)
        result = await db.execute(
            query.order_by(WatchlistEntry.created_at.desc(), WatchlistEntry.id)
            .limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def create(self, db: AsyncSession, user_id: UUID, data: WatchlistCreate) -> WatchlistEntry:
        entry = WatchlistEntry(user_id=user_id, **data.model_dump())
        db.add(entry)
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
        await db.commit()
        await db.refresh(entry)
        return entry

    async def delete(self, db: AsyncSession, entry: WatchlistEntry) -> None:
        await db.delete(entry)
        await db.commit()


crud_watchlist = CRUDWatchlist()
