"""Persist user selections without probing providers or advancing watched counts."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models.playback_history import PlaybackHistory
from backend.database.sсhemas.playback_history import PlaybackHistoryWrite


async def list_history(db: AsyncSession, user_id: UUID, limit: int, offset: int) -> list[PlaybackHistory]:
    result = await db.execute(select(PlaybackHistory).where(PlaybackHistory.user_id == user_id)
                              .order_by(PlaybackHistory.updated_at.desc(), PlaybackHistory.id)
                              .limit(limit).offset(offset))
    return list(result.scalars().all())


async def get_history(db: AsyncSession, user_id: UUID, source: str, external_id: str) -> PlaybackHistory | None:
    result = await db.execute(select(PlaybackHistory).where(
        PlaybackHistory.user_id == user_id,
        PlaybackHistory.anime_source == source,
        PlaybackHistory.anime_external_id == external_id,
    ))
    return result.scalar_one_or_none()


async def save_history(db: AsyncSession, user_id: UUID, source: str, external_id: str,
                       data: PlaybackHistoryWrite) -> PlaybackHistory:
    # Use one atomic statement even when concurrent tabs save the first entry.
    # The synchronous adapter is used only by the existing SQLite HTTP tests.
    session = getattr(db, "session", db)
    dialect = session.get_bind().dialect.name
    insert = postgresql_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
    if insert is None:
        raise RuntimeError("Playback history requires PostgreSQL or SQLite")
    fields = {**data.model_dump(), "updated_at": datetime.now(timezone.utc)}
    statement = insert(PlaybackHistory).values(
        user_id=user_id, anime_source=source, anime_external_id=external_id, **fields,
    ).on_conflict_do_update(
        index_elements=[PlaybackHistory.user_id, PlaybackHistory.anime_source, PlaybackHistory.anime_external_id],
        set_=fields,
    ).returning(PlaybackHistory).execution_options(populate_existing=True)
    result = await db.execute(statement)
    entry = result.scalar_one()
    await db.commit()
    return entry
