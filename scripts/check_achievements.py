"""Check concurrent awards and showcase changes in an isolated PostgreSQL schema."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from backend.core.config import settings
from backend.database.models.user import User, UserProfile
from backend.database.models.achievement import UserAchievement
from backend.database.sсhemas.watchlist import WatchlistCreate
from backend.crud.watchlist import crud_watchlist
from backend.services.achievements import my_achievements, select_showcase
from scripts.check_infrastructure import apply_migrations


async def main():
    assert settings.POSTGRES_HOST in {"localhost", "127.0.0.1", "::1"}, "Local development database only"
    schema = "test_ach_" + uuid4().hex
    control = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    scoped = None
    created = False
    try:
        async with control.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        scoped = create_async_engine(settings.DATABASE_URL, poolclass=NullPool,
            connect_args={"server_settings": {"search_path": schema}, "timeout": 3, "command_timeout": 10})
        async with scoped.begin() as connection:
            await connection.run_sync(apply_migrations)
        sessions = async_sessionmaker(scoped, expire_on_commit=False)
        user_id = uuid4()
        async with sessions() as db:
            db.add(User(id=user_id, username="ach-"+uuid4().hex, email=uuid4().hex+"@example.com",
                        hashed_password="unused-test-hash", email_verified_at=datetime.now(timezone.utc),
                        profile=UserProfile(id=user_id)))
            await db.commit()

        async def awards():
            async with sessions() as db:
                return await my_achievements(db, user_id)

        results = await asyncio.gather(*(awards() for _ in range(4)))
        dates = {next(item["awarded_at"] for item in result if item["code"] == "email_verified") for result in results}
        assert len(dates) == 1

        async def complete(number):
            async with sessions() as db:
                await crud_watchlist.create(db, user_id, WatchlistCreate(anime_external_id=str(number), anime_title="Test", status="completed"))

        await asyncio.gather(complete(1), complete(2))

        async def choose(codes):
            async with sessions() as db:
                return await select_showcase(db, user_id, codes)

        await asyncio.gather(choose(["email_verified", "first_anime"]), choose(["first_anime", "email_verified"]))
        async with sessions() as db:
            rows = (await db.execute(select(UserAchievement).where(UserAchievement.user_id == user_id))).scalars().all()
            assert {row.code for row in rows} == {"email_verified", "first_anime"}
            assert sorted(row.showcase_slot for row in rows) == [1, 2]
        print("PostgreSQL achievements: concurrent awards are unique, timestamps stable, showcase slots consistent")
    finally:
        if scoped:
            await scoped.dispose()
        if created:
            async with control.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await control.dispose()


if __name__ == "__main__":
    asyncio.run(main())
