import unittest
import asyncio
from contextlib import asynccontextmanager
from importlib import import_module
from unittest.mock import AsyncMock, patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.database.models.anime_registry import AnimeRegistry
from backend.database.sсhemas.catalog import AnimeCard, AnimeDetails, CatalogPage, PlaybackMatch
from backend.services import anime_registry as registry, catalog_service
from tests.test_watchlist import AsyncSessionAdapter
from main import app


def card(identifier="877", title="Нана", original="Nana", source="shikimori", slug=None):
    return AnimeCard(source=source, external_id=identifier, title=title, original_title=original, slug=slug)


class AnimeRegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        self.migration = import_module("migrations.versions.0009_anime_registry")
        with self.engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            self.migration.upgrade()
        self.statements, self.storage, self.cache_reads, self.cache_writes = [], {}, [], []
        event.listen(self.engine, "before_cursor_execute", lambda conn, cursor, statement, params, context, many:
                     self.statements.append(statement))

        @asynccontextmanager
        async def sessions():
            with Session(self.engine, expire_on_commit=False) as session:
                yield AsyncSessionAdapter(session)

        async def read(keys):
            self.cache_reads.append(keys)
            return {key: self.storage[key] for key in keys if key in self.storage}

        async def write(values, ttl):
            self.cache_writes.append((values, ttl))
            self.storage.update(values)

        for name, value in [("AsyncSessionLocal", sessions), ("get_cached_json_many", read),
                            ("set_cached_json_many", write)]:
            patcher = patch.object(registry, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def rows(self):
        with Session(self.engine) as db:
            return {row.external_id + ":" + row.source: registry._from_row(row)
                    for row in db.scalars(select(AnimeRegistry)).all()}

    async def test_whole_shelf_uses_two_sql_statements_and_no_sql_on_hot_cache(self):
        cards = [card(str(i), f"Аниме {i}", f"Anime {i}") for i in range(1, 51)]
        await registry.remember_titles(cards)
        self.assertEqual(len(self.statements), 2)
        self.assertTrue(self.statements[0].startswith("SELECT"))
        self.assertTrue(self.statements[1].startswith("INSERT"))
        self.assertEqual(len(self.cache_reads[0]), 50)
        self.assertEqual(self.cache_writes[0][1], 21600)
        self.statements.clear()
        await registry.remember_titles(cards)
        self.assertEqual(self.statements, [])
        self.assertEqual(len(self.rows()), 50)

    async def test_redis_expiry_reads_postgres_and_restores_the_hot_cache(self):
        await registry.remember_titles([card()])
        self.storage.clear()
        self.statements.clear()
        result = await registry.get_title("shikimori", "877")
        self.assertEqual(result.public_path, "/anime/nana-877")
        self.assertEqual(len(self.statements), 1)
        self.statements.clear()
        self.assertEqual((await registry.get_title("shikimori", "877")).public_path, result.public_path)
        self.assertEqual(self.statements, [])

    async def test_renamed_title_updates_metadata_but_never_the_public_slug(self):
        await registry.remember_titles([card()])
        changed = card(title="Нана: новое название", original="Nana: New Name")
        await registry.remember_titles([changed])
        self.assertEqual(changed.public_path, "/anime/nana-877")
        self.assertEqual(self.rows()["877:shikimori"].original_title, "Nana: New Name")
        self.storage.clear()
        cached_page_card = card(title="Нана: новое название", original="Nana: New Name")
        await registry.remember_titles([cached_page_card])
        self.assertEqual(cached_page_card.public_path, "/anime/nana-877")

    async def test_same_numeric_id_in_two_sources_does_not_collide(self):
        first, second = card(), card(source="animego", slug="nana")
        await registry.remember_titles([first, second])
        self.assertEqual(first.public_path, "/anime/nana-877")
        self.assertEqual(second.public_path, "/anime/nana-a877")
        self.assertEqual(len(self.rows()), 2)

    async def test_duplicates_in_one_batch_are_merged_before_upsert(self):
        full, partial = card(), card(original=None)
        await registry.remember_titles([full, partial, full])
        records = self.rows()
        self.assertEqual(len(records), 1)
        self.assertEqual(records["877:shikimori"].original_title, "Nana")
        self.assertEqual(full.public_path, partial.public_path)

    async def test_missing_optional_metadata_does_not_erase_known_upstream_slug(self):
        await registry.remember_titles([card(source="animego", slug="provider-nana")])
        self.storage.clear()
        changed = card(title="Новое название", original="   ", source="animego")
        await registry.remember_titles([changed])
        record = self.rows()["877:animego"]
        self.assertEqual((record.original_title, record.upstream_slug), ("Nana", "provider-nana"))
        self.assertEqual(changed.public_path, "/anime/provider-nana-a877")

    async def test_cold_identical_metadata_is_not_rewritten(self):
        await registry.remember_titles([card()])
        self.storage.clear()
        self.statements.clear()
        await registry.remember_titles([card()])
        self.assertEqual(len(self.statements), 1)
        self.assertTrue(self.statements[0].startswith("SELECT"))

    async def test_conflicting_first_insert_keeps_the_winners_public_slug(self):
        await registry.remember_titles([card()])
        changed = card(title="Другое название", original="A different title")
        self.storage.clear()
        real_select = registry._select
        first = True

        async def concurrent_read(db, identities):
            nonlocal first
            if first:
                first = False
                return {}  # Another transaction inserted after our initial SELECT.
            return await real_select(db, identities)

        with patch.object(registry, "_select", side_effect=concurrent_read):
            await registry.remember_titles([changed])
        self.assertEqual(changed.public_path, "/anime/nana-877")
        self.assertEqual(self.rows()["877:shikimori"].title, "Другое название")

    async def test_wrong_or_malformed_cache_entries_are_reloaded_from_sql(self):
        await registry.remember_titles([card()])
        key = registry._key(("shikimori", "877"))
        for damaged in [{"public_slug": "https://evil.example"},
                        {**self.rows()["877:shikimori"].model_dump(), "external_id": "878"}]:
            self.storage[key] = damaged
            self.assertEqual((await registry.get_title("shikimori", "877")).public_path, "/anime/nana-877")

    async def test_database_outage_preserves_cached_slug_and_does_not_hide_cards(self):
        await registry.remember_titles([card()])
        changed = card(title="Другое название", original="Changed")
        failure = OperationalError("private SQL", {}, Exception("private connection data"))
        with patch.object(registry, "AsyncSessionLocal", side_effect=failure) as connect, \
             self.assertLogs(registry.log, "WARNING") as logs:
            await registry.remember_titles([changed])
            fresh = card("22", "Новый", "New")
            await registry.remember_titles([fresh])
        connect.assert_called_once()
        self.assertEqual(changed.public_path, "/anime/nana-877")
        self.assertEqual(fresh.public_path, "/anime/new-22")
        self.assertNotIn("private", " ".join(logs.output))

    async def test_slow_database_has_a_deadline_and_returns_a_usable_fallback(self):
        @asynccontextmanager
        async def stalled():
            await asyncio.Event().wait()
            yield None

        item = card()
        with patch.object(registry, "AsyncSessionLocal", stalled), \
             patch.object(registry, "DB_TIMEOUT_SECONDS", 0.01), self.assertLogs(registry.log, "WARNING"):
            await registry.remember_titles([item])
        self.assertEqual(item.public_path, "/anime/nana-877")
        self.assertEqual(self.statements, [])

    async def test_large_results_are_bounded_batches_instead_of_one_query_per_card(self):
        await registry.remember_titles([card(str(i)) for i in range(1, 206)])
        self.assertEqual(len(self.statements), 6)
        self.assertEqual([len(keys) for keys in self.cache_reads], [100, 100, 5])

    async def test_invalid_source_or_identifier_never_queries_sql(self):
        await registry.remember_titles([card("0"), card(source="kodik")])
        self.assertIsNone(await registry.get_title("other", "877"))
        self.assertEqual(await registry.lookup_titles([("shikimori", "../877")]), {})
        self.assertEqual(self.statements, [])

    async def test_legacy_redirect_uses_database_when_redis_and_upstream_metadata_are_absent(self):
        await registry.remember_titles([card()])
        self.storage.clear()
        with patch.object(catalog_service, "cached_shiki", AsyncMock(side_effect=AssertionError("must not fetch"))):
            self.assertEqual(await catalog_service.legacy_anime_path("shikimori", "877"), "/anime/nana-877")

    async def test_cached_detail_page_uses_the_persistent_slug_after_title_changes(self):
        await registry.remember_titles([card()])
        details = AnimeDetails(**card(title="Новое название", original="Changed").model_dump())
        page = CatalogPage(details=details, playback=PlaybackMatch(status="not_found"))
        self.storage.clear()
        with patch.object(catalog_service, "get_cached_json", AsyncMock(return_value=page.model_dump(mode="json"))), \
             patch.object(catalog_service, "apply_posters", AsyncMock()), \
             patch.object(catalog_service, "remember_playback_identity", AsyncMock()):
            result = await catalog_service.catalog_page("shikimori", "877")
        self.assertEqual(result.details.public_path, "/anime/nana-877")

    async def test_upstream_slug_survives_missing_animego_redis_card(self):
        title = AnimeCard(source="animego", external_id="1939", title="Аполлон: Дети на холме",
                          original_title="Sakamichi no Apollon", slug="apollon-deti-na-holme")
        await registry.remember_titles([title])
        self.storage.clear()
        payload = {"id": "1939", "title": title.title, "original_title": title.original_title,
                   "slug": title.slug, "year": 2012, "type": "Сериал"}
        with patch.object(catalog_service, "get_cached_json", AsyncMock(return_value=None)), \
             patch.object(catalog_service, "_run_sync", AsyncMock(return_value={"title": title.title})) as load, \
             patch.object(catalog_service, "search_animego", AsyncMock(return_value=[payload])), \
             patch.object(catalog_service, "cached_shiki", AsyncMock(side_effect=HTTPException(503, "offline"))):
            page = await catalog_service.animego_page("1939", "some-other-readable-name")
        self.assertTrue(load.await_args.args[1].endswith("/anime/apollon-deti-na-holme-1939"))
        self.assertEqual(page.details.slug, title.slug)

    async def test_search_endpoint_persists_real_cards_and_returns_stable_links(self):
        payload = {"id": "308", "title": "Нана", "original_title": "Nana", "slug": "nana"}
        with TestClient(app) as client, patch("backend.api.v1.endpoints.anime.search_animego", AsyncMock(return_value=[payload])):
            response = client.get("/api/v1/anime/animego/search", params={"q": "Нана"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[0]["public_path"], "/anime/nana-a308")
        self.assertEqual(self.rows()["308:animego"].upstream_slug, "nana")

    async def test_migration_has_composite_identity_and_can_be_reversed(self):
        columns = {column["name"] for column in inspect(self.engine).get_columns("anime_registry")}
        self.assertTrue({"public_slug", "upstream_slug", "created_at", "updated_at"}.issubset(columns))
        self.assertEqual(inspect(self.engine).get_pk_constraint("anime_registry")["constrained_columns"], ["source", "external_id"])
        with self.engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            self.migration.downgrade()
        self.assertNotIn("anime_registry", inspect(self.engine).get_table_names())
