"""Public provider work is bounded on the VPS, without changing local defaults."""
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from backend.core.config import Settings, settings
from backend.core.rate_limit import get_rate_limiter, limited_catalog_read
from main import app


class ProductionConfigTests(unittest.TestCase):
    def test_database_credentials_with_reserved_characters_survive_url_roundtrip(self):
        config = Settings(_env_file=None, SECRET_KEY="test-secret-key-at-least-32-characters",
                          POSTGRES_USER="test@user", POSTGRES_PASSWORD="test@:/%#password",
                          POSTGRES_DB="test_db")
        url = make_url(config.DATABASE_URL)
        self.assertEqual(url.username, "test@user")
        self.assertEqual(url.password, "test@:/%#password")
        from configparser import ConfigParser
        parser = ConfigParser()
        parser["alembic"] = {"sqlalchemy.url": config.DATABASE_URL.replace("%", "%%")}
        self.assertEqual(parser.get("alembic", "sqlalchemy.url"), config.DATABASE_URL)


class PublicCatalogLimitTests(unittest.TestCase):
    def test_production_limit_rejects_before_starting_provider_work(self):
        limiter = AsyncMock()
        limiter.check.side_effect = HTTPException(429, "Too many requests", headers={"Retry-After": "12"})
        previous = app.dependency_overrides.copy()
        app.dependency_overrides[get_rate_limiter] = lambda: limiter
        try:
            with patch.object(settings, "ENABLE_CATALOG_RATE_LIMIT", True), \
                    patch("backend.api.v1.endpoints.anime.search_animego", AsyncMock()) as provider, \
                    TestClient(app) as client:
                response = client.get("/api/v1/anime/animego/search", params={"q": "Naruto"})
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.headers["Retry-After"], "12")
                provider.assert_not_awaited()
                limiter.check.assert_awaited_once()
                self.assertEqual(limiter.check.await_args.args[0][0][1:], (120, 60000))
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)


class LocalCatalogLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_development_does_not_depend_on_the_production_read_limiter(self):
        limiter = AsyncMock()
        with patch.object(settings, "ENABLE_CATALOG_RATE_LIMIT", False):
            await limited_catalog_read(None, limiter)
        limiter.check.assert_not_awaited()
