import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from backend.services import health
from main import app


class HealthHTTPTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_liveness_does_not_touch_dependencies(self):
        with patch.object(health, "check_database", AsyncMock(side_effect=AssertionError("no database"))) as database, \
                patch.object(health, "check_redis", AsyncMock(side_effect=AssertionError("no redis"))) as redis:
            response = self.client.get("/health/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        database.assert_not_called()
        redis.assert_not_called()

    def test_readiness_requires_both_local_dependencies(self):
        for database_ready, redis_ready, status in ((True, True, 200), (False, True, 503),
                                                   (True, False, 503), (False, False, 503)):
            with self.subTest(database=database_ready, redis=redis_ready):
                with patch.object(health, "check_database", AsyncMock(return_value=database_ready)), \
                        patch.object(health, "check_redis", AsyncMock(return_value=redis_ready)):
                    response = self.client.get("/health/ready")
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json(), {
                    "status": "ok" if status == 200 else "unavailable",
                    "checks": {"database": database_ready, "redis": redis_ready},
                })
                self.assertEqual(response.headers["cache-control"], "no-store")

    def test_driver_errors_are_unavailable_without_leaking_connection_details(self):
        private_error = RuntimeError("postgresql://admin:private-password@internal.example/private-db")
        with patch.object(health, "check_database", AsyncMock(side_effect=private_error)), \
                patch.object(health, "check_redis", AsyncMock(side_effect=ConnectionError("redis-secret"))):
            response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {
            "status": "unavailable", "checks": {"database": False, "redis": False},
        })
        self.assertNotIn("private-password", response.text)
        self.assertNotIn("internal.example", response.text)
        self.assertNotIn("redis-secret", response.text)


class HealthProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_checks_select_one_and_releases_connection(self):
        connection = AsyncMock()
        connection.scalar.return_value = 1
        context = AsyncMock()
        context.__aenter__.return_value = connection
        fake_engine = MagicMock()
        fake_engine.connect.return_value = context
        with patch.object(health, "engine", fake_engine):
            self.assertTrue(await health.check_database())
        fake_engine.connect.assert_called_once_with()
        connection.scalar.assert_awaited_once()
        self.assertEqual(str(connection.scalar.await_args.args[0]), "SELECT 1")
        context.__aexit__.assert_awaited_once()

    async def test_redis_checks_ping_only(self):
        redis = AsyncMock()
        redis.ping.return_value = True
        with patch.object(health, "redis_client", redis):
            self.assertTrue(await health.check_redis())
            redis.ping.return_value = False
            self.assertFalse(await health.check_redis())
        self.assertEqual(redis.ping.await_count, 2)
        redis.set.assert_not_awaited()

    async def test_deadline_is_shared_and_preserves_completed_checks(self):
        database_started, redis_started = asyncio.Event(), asyncio.Event()
        cancelled = asyncio.Event()

        async def waiting_database():
            database_started.set()
            await redis_started.wait()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def available_redis():
            redis_started.set()
            await database_started.wait()
            return True

        with patch.object(health, "READINESS_TIMEOUT_SECONDS", 0.02), \
                patch.object(health, "check_database", waiting_database), \
                patch.object(health, "check_redis", available_redis):
            started = time.monotonic()
            checks = await health.readiness_checks()
            elapsed = time.monotonic() - started
            await asyncio.wait_for(cancelled.wait(), timeout=0.2)
        self.assertEqual(checks, {"database": False, "redis": True})
        self.assertLess(elapsed, 0.2)

    async def test_slow_driver_cleanup_does_not_extend_response_deadline(self):
        cleanup_started, release_cleanup = asyncio.Event(), asyncio.Event()

        async def slow_database():
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await release_cleanup.wait()

        with patch.object(health, "READINESS_TIMEOUT_SECONDS", 0.01), \
                patch.object(health, "check_database", slow_database), \
                patch.object(health, "check_redis", AsyncMock(return_value=True)):
            try:
                checks = await asyncio.wait_for(health.readiness_checks(), timeout=0.2)
                self.assertEqual(checks, {"database": False, "redis": True})
                await asyncio.wait_for(cleanup_started.wait(), timeout=0.2)
            finally:
                release_cleanup.set()
                await asyncio.gather(*tuple(health._cleaning_probes), return_exceptions=True)

    async def test_cancelled_request_cancels_its_running_probes(self):
        started = [asyncio.Event(), asyncio.Event()]
        cancelled = [asyncio.Event(), asyncio.Event()]

        async def probe(index):
            started[index].set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled[index].set()

        with patch.object(health, "check_database", lambda: probe(0)), \
                patch.object(health, "check_redis", lambda: probe(1)):
            task = asyncio.create_task(health.readiness_checks())
            await asyncio.gather(*(event.wait() for event in started))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in cancelled)), timeout=0.2)
