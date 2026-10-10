"""Exercise HTTP routes and real SQL using a disposable SQLite database.

The adapter exposes async session calls for synchronous SQLite. PostgreSQL
migration execution and asyncpg still require a separate integration run.
"""
import unittest
from importlib import import_module
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.core.database import get_db
from backend.core.password import get_password_hash
from backend.core.security import create_access_token
from backend.database.models.user import User, UserProfile
from backend.database.models.watchlist import WatchlistEntry
from main import app


class AsyncSessionAdapter:
    def __init__(self, session):
        self.session = session

    def add(self, value):
        self.session.add(value)

    async def execute(self, statement):
        return self.session.execute(statement)

    async def flush(self):
        self.session.flush()

    async def commit(self):
        self.session.commit()

    async def refresh(self, value):
        self.session.refresh(value)

    async def rollback(self):
        self.session.rollback()

    async def delete(self, value):
        self.session.delete(value)


class DatabaseAPITestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = get_password_hash("test-password-123")

    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                import_module("migrations.versions.0001_initial").upgrade()
                import_module("migrations.versions.0002_watchlist").upgrade()
                import_module("migrations.versions.0003_discussion").upgrade()
        self.owner_id, self.other_id = uuid4(), uuid4()
        with Session(self.engine) as session:
            for user_id, name in [(self.owner_id, "owner"), (self.other_id, "other")]:
                session.add(User(
                    id=user_id, username=name, email=f"{name}@example.com",
                    hashed_password=self.password_hash, profile=UserProfile(id=user_id),
                ))
            session.commit()

        async def test_db():
            with Session(self.engine, expire_on_commit=False) as session:
                try:
                    yield AsyncSessionAdapter(session)
                except Exception:
                    session.rollback()
                    raise

        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = test_db
        self.revoked = set()

        async def revoke(key, ttl, value):
            self.revoked.add(key)

        self.redis = AsyncMock()
        self.redis.exists.side_effect = lambda key: key in self.revoked
        self.redis.setex.side_effect = revoke
        self.redis_patch = patch("backend.core.security.redis_client", self.redis)
        self.redis_patch.start()
        self.client = TestClient(app)
        self.owner_headers = {"Authorization": f"Bearer {create_access_token(self.owner_id)}"}
        self.other_headers = {"Authorization": f"Bearer {create_access_token(self.other_id)}"}

    def tearDown(self):
        self.client.close()
        self.redis_patch.stop()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)
        self.engine.dispose()

class WatchlistTests(DatabaseAPITestCase):
    path = "/api/v1/users/me/watchlist"

    def add_entry(self, anime_id="20", headers=None, **fields):
        response = self.client.post(
            self.path,
            headers=self.owner_headers if headers is None else headers,
            json={"anime_external_id": anime_id, "anime_title": "Naruto", **fields},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_update_list_delete(self):
        entry = self.add_entry()
        self.assertEqual(entry["status"], "planned")
        self.assertEqual(entry["episodes_watched"], 0)
        self.assertEqual(entry["user_id"], str(self.owner_id))
        response = self.client.patch(
            f'{self.path}/{entry["id"]}', headers=self.owner_headers,
            json={"status": "watching", "episodes_watched": 12},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["episodes_watched"], 12)
        self.assertEqual(response.json()["anime_external_id"], "20")
        entries = self.client.get(self.path, headers=self.owner_headers).json()
        self.assertEqual(entries[0]["status"], "watching")
        response = self.client.delete(f'{self.path}/{entry["id"]}', headers=self.owner_headers)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertEqual(self.client.get(self.path, headers=self.owner_headers).json(), [])

    def test_duplicate_conflict_and_source_identity(self):
        self.add_entry()
        duplicate = self.client.post(
            self.path, headers=self.owner_headers,
            json={"anime_external_id": " 20 ", "anime_title": "Naruto"},
        )
        self.assertEqual(duplicate.status_code, 409)
        self.add_entry(anime_source="animego")
        self.add_entry(headers=self.other_headers)
        self.assertEqual(len(self.client.get(self.path, headers=self.owner_headers).json()), 2)

    def test_other_user_cannot_modify_or_delete_entry(self):
        entry = self.add_entry()
        path = f'{self.path}/{entry["id"]}'
        response = self.client.patch(path, headers=self.other_headers, json={"status": "dropped"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.delete(path, headers=self.other_headers).status_code, 404)
        self.assertEqual(self.client.get(self.path, headers=self.other_headers).json(), [])
        self.assertEqual(len(self.client.get(self.path, headers=self.owner_headers).json()), 1)

    def test_privacy_toggle_and_owner_access(self):
        self.add_entry()
        path = f"/api/v1/users/{self.owner_id}/watchlist"
        self.assertEqual(self.client.get(path, headers=self.owner_headers).status_code, 200)
        self.assertEqual(self.client.get(path, headers=self.other_headers).status_code, 403)
        response = self.client.patch(
            "/api/v1/profile/settings", headers=self.owner_headers,
            json={"show_watchlist": True},
        )
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.get(path, headers=self.other_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_filter_and_pagination(self):
        self.add_entry("20", status="watching")
        self.add_entry("21", status="watching")
        self.add_entry("22", status="completed")
        response = self.client.get(self.path, headers=self.owner_headers, params={"status": "watching"})
        self.assertEqual(response.status_code, 200)
        entries = response.json()
        self.assertEqual(len(entries), 2)
        page = self.client.get(
            self.path, headers=self.owner_headers, params={"status": "watching", "limit": 1, "offset": 1},
        ).json()
        self.assertEqual(page, entries[1:])
        for params in [{"limit": 101}, {"offset": -1}, {"status": "unknown"}]:
            self.assertEqual(self.client.get(self.path, headers=self.owner_headers, params=params).status_code, 422)

    def test_invalid_values_and_immutable_identity(self):
        for fields in [
            {"anime_title": "  "}, {"anime_external_id": " "},
            {"status": "unknown"}, {"episodes_watched": -1},
            {"episodes_watched": True}, {"episodes_watched": 1.5},
            {"episodes_watched": 2147483648}, {"anime_source": "unknown"},
            {"user_id": str(self.other_id)},
        ]:
            with self.subTest(fields=fields):
                response = self.client.post(self.path, headers=self.owner_headers, json={
                    "anime_external_id": "20", "anime_title": "Naruto", **fields,
                })
                self.assertEqual(response.status_code, 422, response.text)
        entry = self.add_entry()
        for fields in [
            {"status": None}, {"anime_title": None}, {"episodes_watched": None},
            {"anime_external_id": "21"}, {"user_id": str(self.other_id)},
        ]:
            with self.subTest(fields=fields):
                response = self.client.patch(
                    f'{self.path}/{entry["id"]}', headers=self.owner_headers, json=fields,
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_missing_user_and_entry(self):
        path = f"{self.path}/{uuid4()}"
        self.assertEqual(self.client.patch(path, headers=self.owner_headers, json={"status": "watching"}).status_code, 404)
        self.assertEqual(self.client.delete(path, headers=self.owner_headers).status_code, 404)
        self.assertEqual(self.client.get(
            f"/api/v1/users/{uuid4()}/watchlist", headers=self.owner_headers,
        ).status_code, 404)

    def test_authentication_required(self):
        entry = self.add_entry()
        self.assertEqual(self.client.get(self.path).status_code, 401)
        self.assertEqual(self.client.post(self.path, json={}).status_code, 401)
        self.assertEqual(self.client.patch(f'{self.path}/{entry["id"]}', json={}).status_code, 401)
        self.assertEqual(self.client.delete(f'{self.path}/{entry["id"]}').status_code, 401)
        self.assertEqual(self.client.get(f"/api/v1/users/{self.owner_id}/watchlist").status_code, 401)

    def test_migration_downgrade_and_upgrade(self):
        migration = import_module("migrations.versions.0002_watchlist")
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
                self.assertNotIn("watchlist_entries", inspect(connection).get_table_names())
                self.assertIn("users", inspect(connection).get_table_names())
                migration.upgrade()
        self.add_entry()

    def test_deleting_user_cascades_to_watchlist(self):
        self.add_entry()
        with Session(self.engine) as session:
            session.delete(session.get(User, self.owner_id))
            session.commit()
            self.assertEqual(session.query(WatchlistEntry).count(), 0)

    def test_registration_login_profile_watchlist_review_logout(self):
        response = self.client.post("/api/v1/auth/register", json={
            "username": "newuser", "email": "newuser@example.com", "password": "test-password-123",
        })
        self.assertEqual(response.status_code, 201, response.text)
        user_id = response.json()["id"]
        response = self.client.post("/api/v1/auth/login", json={
            "username": "newuser", "password": "test-password-123",
        })
        self.assertEqual(response.status_code, 200, response.text)
        headers = {"Authorization": f'Bearer {response.json()["access_token"]}'}
        response = self.client.get("/api/v1/auth/me", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["profile"]["id"], user_id)
        self.add_entry(headers=headers)
        response = self.client.post("/api/v1/reviews/", headers=headers, json={
            "anime_external_id": "20", "anime_title": "Naruto", "title": "Впечатления", "has_spoilers": False, "text": "слово " * 250, "rating": 8,
        })
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers=headers).status_code, 204)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 401)
        self.assertEqual(self.client.get(self.path, headers=headers).status_code, 401)
