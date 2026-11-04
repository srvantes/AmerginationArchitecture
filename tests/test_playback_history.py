"""Private resume state uses real SQL without changing watched progress."""
from datetime import datetime, timedelta, timezone
from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from backend.core.security import create_access_token
from backend.database.models.user import User
from tests.test_watchlist import DatabaseAPITestCase


class PlaybackHistoryTests(DatabaseAPITestCase):
    path = "/api/v1/users/me/playback-history"

    def setUp(self):
        super().setUp()
        self.migration = import_module("migrations.versions.0008_playback_history")
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                self.migration.upgrade()

    def payload(self, **fields):
        return {
            "anime_title": "Ван-Пис", "poster_url": "https://example.com/one-piece.jpg",
            "anime_slug": "one-piece", "episode": 1000, "player": "kodik",
            "translation_id": "7", "translation_name": "AniMedia", **fields,
        }

    def save(self, anime_id="21", source="shikimori", headers=None, **fields):
        response = self.client.put(
            f"{self.path}/{source}/{anime_id}",
            headers=self.owner_headers if headers is None else headers,
            json=self.payload(**fields),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        return response.json()

    def test_upsert_restores_exact_choice_without_duplicate_entries(self):
        original = self.save()
        self.assertEqual(original["anime_source"], "shikimori")
        self.assertEqual(original["anime_external_id"], "21")
        self.assertNotIn("user_id", original)
        self.assertTrue(original["updated_at"])
        changed = self.save(episode=1001, player="aniboom", translation_id="9", translation_name="2x2")
        self.assertEqual(changed["id"], original["id"])
        response = self.client.get(self.path + "/shikimori/21", headers=self.owner_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), changed)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(changed["episode"], 1001)
        self.assertEqual(changed["player"], "aniboom")
        self.assertEqual(changed["translation_id"], "9")
        self.assertEqual(changed["translation_name"], "2x2")
        entries = self.client.get(self.path, headers=self.owner_headers)
        self.assertEqual(entries.status_code, 200)
        self.assertEqual(entries.json(), [changed])
        self.assertEqual(entries.headers["cache-control"], "private, no-store")

    def test_identity_includes_source_and_owner(self):
        owner = self.save()
        self.save(source="animego", episode=13)
        path = self.path + "/shikimori/21"
        response = self.client.get(path, headers=self.other_headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(self.client.get(self.path, headers=self.other_headers).json(), [])
        other = self.save(headers=self.other_headers, episode=2)
        self.assertNotEqual(other["id"], owner["id"])
        self.assertEqual(self.client.get(path, headers=self.owner_headers).json()["episode"], 1000)
        self.assertEqual(self.client.get(path, headers=self.other_headers).json()["episode"], 2)
        self.assertEqual(len(self.client.get(self.path, headers=self.owner_headers).json()), 2)
        self.assertEqual(len(self.client.get(self.path, headers=self.other_headers).json()), 1)

    def test_history_stays_private_when_watchlist_is_public(self):
        self.save()
        settings = self.client.patch("/api/v1/profile/settings", headers=self.owner_headers,
                                     json={"show_watchlist": True})
        self.assertEqual(settings.status_code, 200, settings.text)
        guessed = f"/api/v1/users/{self.owner_id}/playback-history"
        for headers in ({}, self.other_headers):
            self.assertEqual(self.client.get(guessed, headers=headers).status_code, 404)
        self.assertEqual(self.client.get(self.path + "/shikimori/21", headers=self.other_headers).status_code, 404)

    def test_authentication_required_and_expired_or_revoked_tokens_rejected(self):
        self.save()
        expired = create_access_token(self.owner_id, expires_delta=timedelta(seconds=-1))
        expired_headers = {"Authorization": "Bearer " + expired}
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers=self.owner_headers).status_code, 204)
        for headers in ({}, expired_headers, self.owner_headers):
            for method, path in (("GET", self.path), ("GET", self.path + "/shikimori/21"),
                                 ("PUT", self.path + "/shikimori/21")):
                with self.subTest(headers=bool(headers), method=method, path=path):
                    response = self.client.request(method, path, headers=headers,
                                                   **({"json": self.payload()} if method == "PUT" else {}))
                    self.assertEqual(response.status_code, 401, response.text)
                    self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_missing_entry_returns_404_and_empty_list(self):
        response = self.client.get(self.path + "/shikimori/21", headers=self.owner_headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(self.client.get(self.path, headers=self.owner_headers).json(), [])

    def test_latest_opened_first_and_pagination(self):
        from backend.database.models.playback_history import PlaybackHistory

        for anime_id in ("20", "21", "22"):
            self.save(anime_id)
        self.save("99", headers=self.other_headers)
        with Session(self.engine) as db:
            for entry in db.query(PlaybackHistory).filter_by(user_id=self.owner_id):
                entry.updated_at = datetime(2026, 1, int(entry.anime_external_id), tzinfo=timezone.utc)
            db.commit()
        response = self.client.get(self.path, headers=self.owner_headers, params={"limit": 2, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([entry["anime_external_id"] for entry in response.json()], ["22", "21"])
        page = self.client.get(self.path, headers=self.owner_headers, params={"limit": 2, "offset": 2})
        self.assertEqual([entry["anime_external_id"] for entry in page.json()], ["20"])
        self.assertEqual(self.client.get(self.path, headers=self.owner_headers, params={"offset": 3}).json(), [])
        self.save("20", episode=5)
        newest = self.client.get(self.path, headers=self.owner_headers, params={"limit": 1}).json()
        self.assertEqual(newest[0]["anime_external_id"], "20")
        self.assertEqual(newest[0]["episode"], 5)
        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            self.assertEqual(self.client.get(self.path, headers=self.owner_headers, params=params).status_code, 422)

    def test_opening_episode_does_not_create_or_change_watchlist_progress(self):
        self.save()
        watchlist = "/api/v1/users/me/watchlist"
        self.assertEqual(self.client.get(watchlist, headers=self.owner_headers).json(), [])
        response = self.client.post(watchlist, headers=self.owner_headers, json={
            "anime_source": "shikimori", "anime_external_id": "21", "anime_title": "Ван-Пис",
            "episodes_watched": 6, "status": "on_hold",
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.save(episode=1100)
        entries = self.client.get(watchlist, headers=self.owner_headers).json()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "on_hold")
        self.assertEqual(entries[0]["episodes_watched"], 6)

    def test_strict_payload_validation_preserves_existing_entry(self):
        original = self.save()
        invalid_fields = [
            {"episode": value} for value in (0, -1, 100001, True, 1.5, "3", None)
        ] + [
            {"translation_id": value} for value in ("0", "-7", "07", "x", "1" * 21, 7, None)
        ] + [
            {"anime_title": "  "}, {"anime_title": "x" * 201},
            {"translation_name": "  "}, {"translation_name": "x" * 201},
            {"player": "unknown"}, {"player": None},
            {"poster_url": "javascript:alert(1)"}, {"poster_url": "data:image/png;base64,abcd"},
            {"poster_url": "file:///private/image.png"}, {"poster_url": "//example.com/poster.jpg"},
            {"poster_url": "https://user:password@example.com/poster.jpg"},
            {"anime_slug": "../../admin"}, {"anime_slug": "x" * 301},
            {"user_id": str(self.other_id)}, {"episodes_watched": 1000},
            {"embed_url": "https://untrusted.example/player"},
            {"anime_source": "animego"}, {"anime_external_id": "22"},
        ]
        for fields in invalid_fields:
            with self.subTest(fields=fields):
                response = self.client.put(self.path + "/shikimori/21", headers=self.owner_headers,
                                           json=self.payload(**fields))
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(self.client.get(self.path + "/shikimori/21", headers=self.owner_headers).json(), original)

    def test_path_identity_validation_and_upper_bounds(self):
        for source, anime_id in (("kodik", "21"), ("other", "21"), ("shikimori", "0"),
                                 ("shikimori", "-1"), ("shikimori", "021"), ("shikimori", "name"),
                                 ("animego", "1" * 21)):
            path = f"{self.path}/{source}/{anime_id}"
            for method in ("GET", "PUT"):
                with self.subTest(method=method, source=source, anime_id=anime_id):
                    response = self.client.request(method, path, headers=self.owner_headers,
                                                   **({"json": self.payload()} if method == "PUT" else {}))
                    self.assertEqual(response.status_code, 422, response.text)
        entry = self.save("9" * 20, episode=100000, translation_id="9" * 20,
                          poster_url=None, anime_slug=None)
        self.assertEqual(entry["episode"], 100000)
        self.assertIsNone(entry["poster_url"])
        self.assertIsNone(entry["anime_slug"])

    def test_deleting_user_cascades_only_their_history(self):
        from backend.database.models.playback_history import PlaybackHistory

        self.save()
        other = self.save(headers=self.other_headers)
        with Session(self.engine) as db:
            db.delete(db.get(User, self.owner_id))
            db.commit()
            entries = db.query(PlaybackHistory).all()
            self.assertEqual(len(entries), 1)
            self.assertEqual(str(entries[0].id), other["id"])

    def test_migration_can_be_reverted_and_applied_without_touching_watchlist(self):
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                self.migration.downgrade()
                tables = inspect(connection).get_table_names()
                self.assertNotIn("playback_history", tables)
                self.assertIn("watchlist_entries", tables)
                self.assertIn("users", tables)
                self.migration.upgrade()
        self.save()
