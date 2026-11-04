"""Explicit PostgreSQL checks; all writes stay in a rollback-only temp table.

Run: python -m unittest tests.integration_anime_registry -q
Requires migrations applied to the configured development database.
"""
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.core.config import settings
from backend.database.sсhemas.catalog import AnimeCard
from backend.services import anime_registry as registry, catalog_service


class PostgresAnimeRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.addAsyncCleanup(self.engine.dispose)
        self.connection = await self.engine.connect()
        self.addAsyncCleanup(self.connection.close)
        self.transaction = await self.connection.begin()
        self.addAsyncCleanup(self.transaction.rollback)
        await self.connection.exec_driver_sql("CREATE TEMP TABLE anime_registry "
                                              "(LIKE public.anime_registry INCLUDING ALL) ON COMMIT DROP")
        persistence = await self.connection.exec_driver_sql("SELECT relpersistence::text FROM pg_class WHERE oid = 'anime_registry'::regclass")
        self.assertEqual(persistence.scalar_one(), "t")
        self.storage, self.sql = {}, []
        event.listen(self.engine.sync_engine, "before_cursor_execute", lambda c, cursor, sql, params, ctx, many:
                     self.sql.append(sql) if sql.startswith(("SELECT", "INSERT")) else None)

        @asynccontextmanager
        async def sessions():
            async with AsyncSession(bind=self.connection, expire_on_commit=False,
                                    join_transaction_mode="create_savepoint") as db:
                yield db

        async def read(keys):
            return {key: self.storage[key] for key in keys if key in self.storage}

        async def write(values, ttl):
            self.storage.update(values)

        self.patchers = [patch.object(registry, name, value) for name, value in [
            ("AsyncSessionLocal", sessions), ("get_cached_json_many", read), ("set_cached_json_many", write)]]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_postgres_bulk_upsert_and_hot_cache_have_no_per_card_queries(self):
        cards = [AnimeCard(source="shikimori", external_id=str(i), title=f"Anime {i}") for i in range(1, 51)]
        await registry.remember_titles(cards)
        self.assertEqual(len(self.sql), 2)
        self.sql.clear()
        await registry.remember_titles(cards)
        self.assertEqual(self.sql, [])

    async def test_postgres_on_conflict_returning_keeps_the_first_slug(self):
        await registry.remember_titles([AnimeCard(source="shikimori", external_id="877", title="Nana")])
        self.storage.clear()
        changed = AnimeCard(source="shikimori", external_id="877", title="Renamed Nana")
        # Exercise an INSERT conflict after another transaction won the initial
        # registration. PostgreSQL must RETURN the stored slug, not our candidate.
        with patch.object(registry, "_select", AsyncMock(return_value={})):
            await registry.remember_titles([changed])
        self.assertEqual(changed.public_path, "/anime/nana-877")

    async def test_postgres_restores_legacy_navigation_after_redis_expiry(self):
        await registry.remember_titles([AnimeCard(source="shikimori", external_id="877", title="Nana")])
        self.storage.clear()
        with patch.object(catalog_service, "cached_shiki", AsyncMock(side_effect=AssertionError("no upstream"))):
            self.assertEqual(await catalog_service.legacy_anime_path("shikimori", "877"), "/anime/nana-877")
