import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from starlette.requests import Request

from backend.core.config import settings
from backend.core.rate_limit import RedisRateLimiter, get_rate_limiter, policy, client_ip, identity
from backend.crud.user import crud_user
from backend.database.models.comment import Comment
from tests.test_watchlist import DatabaseAPITestCase
from main import app


class RateLimitUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_after_rounds_up_and_changes_per_response(self):
        client = AsyncMock()
        client.eval.side_effect = [15001, 900]
        limiter = RedisRateLimiter(client)
        for expected in (16, 1):
            with self.assertRaises(HTTPException) as caught:
                await limiter.check([policy("test", "user", 1, 15)])
            self.assertEqual(caught.exception.status_code, 429)
            self.assertEqual(caught.exception.headers["Retry-After"], str(expected))
            self.assertIn(str(expected), caught.exception.detail)

    async def test_redis_failure_blocks_writes_with_retry_after(self):
        client = AsyncMock()
        client.eval.side_effect = RedisConnectionError("offline")
        with self.assertRaises(HTTPException) as caught:
            await RedisRateLimiter(client).check([policy("test", "user", 1, 15)])
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.headers["Retry-After"], "5")

    async def test_policies_use_single_eval_unique_members_and_private_keys(self):
        client = AsyncMock()
        client.eval.return_value = 0
        policies = [policy("comments", "user-id", 20, 3600), policy("cooldown", "user-id", 1, 15)]
        limiter = RedisRateLimiter(client)
        await limiter.check(policies)
        await limiter.check(policies)
        first, second = [call.args for call in client.eval.await_args_list]
        self.assertEqual(first[1], 2)
        self.assertNotIn("user-id", first[2])
        self.assertNotEqual(first[4], second[4])
        self.assertEqual(first[5:], (20, 3600000, 1, 15000))

    def test_forwarded_headers_cannot_spoof_identity(self):
        request = Request({"type": "http", "client": ("127.0.0.1", 1234),
                           "headers": [(b"x-forwarded-for", b"8.8.8.8"), (b"x-real-ip", b"1.1.1.1")]})
        self.assertEqual(client_ip(request), "127.0.0.1")
        self.assertNotEqual(identity("user-a"), identity("user-b"))


class RateLimitRouteTests(DatabaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.limit_redis = AsyncMock()
        self.limit_redis.eval.return_value = 15000
        app.dependency_overrides[get_rate_limiter] = lambda: RedisRateLimiter(self.limit_redis)

    def test_registration_and_login_stop_before_database_changes_or_hashing(self):
        with patch.object(crud_user, "authenticate", AsyncMock()) as authenticate:
            result = self.client.post("/api/v1/auth/login", json={"username": "owner", "password": "test-password-123"})
        self.assertEqual(result.status_code, 429, result.text)
        authenticate.assert_not_awaited()
        result = self.client.post("/api/v1/auth/register", json={"username": "newuser", "email": "new@example.com", "password": "test-password-123"})
        self.assertEqual(result.status_code, 429, result.text)
        self.assertEqual(result.headers["Retry-After"], "15")

    def test_protected_discussion_actions_are_limited(self):
        comment_id = str(uuid4())
        cases = [
            ("post", "/api/v1/comments/", {"anime_source": "shikimori", "anime_external_id": "20", "text": "Комментарий"}),
            ("patch", "/api/v1/comments/" + comment_id, {"text": "Правка"}),
            ("delete", "/api/v1/comments/" + comment_id, None),
            ("put", "/api/v1/comments/" + comment_id + "/like", None),
            ("delete", "/api/v1/comments/" + comment_id + "/like", None),
            ("post", "/api/v1/reviews/", {"anime_source": "shikimori", "anime_external_id": "20", "anime_title": "Наруто", "title": "Рецензия", "text": "слово " * 250, "has_spoilers": False}),
            ("patch", "/api/v1/reviews/" + comment_id, {"title": "Правка"}),
            ("delete", "/api/v1/reviews/" + comment_id, None),
        ]
        for method, path, body in cases:
            args = {"json": body} if body is not None else {}
            result = getattr(self.client, method)(path, headers=self.owner_headers, **args)
            self.assertEqual(result.status_code, 429, (path, result.text))
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Comment)), 0)

    def test_reading_and_auth_checks_do_not_use_mutation_budgets(self):
        params = {"anime_source": "shikimori", "anime_external_id": "20"}
        for path in ("/api/v1/comments/", "/api/v1/reviews/"):
            self.assertEqual(self.client.get(path, params=params).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/comments/", json={"anime_source": "shikimori", "anime_external_id": "20", "text": "Текст"}).status_code, 401)
        self.limit_redis.eval.assert_not_awaited()

    def test_redis_outage_returns_503_and_public_discussion_still_works(self):
        self.limit_redis.eval.side_effect = RedisConnectionError("offline")
        result = self.client.post("/api/v1/comments/", headers=self.owner_headers, json={"anime_source": "shikimori", "anime_external_id": "20", "text": "Комментарий"})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.headers["Retry-After"], "5")
        self.assertEqual(self.client.get("/api/v1/comments/", params={"anime_source": "shikimori", "anime_external_id": "20"}).status_code, 200)


@unittest.skipUnless(os.environ.get("RUN_REDIS_RATE_LIMIT_TESTS") == "1", "Opt-in real Redis integration")
class RedisWindowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT,
                            password=settings.REDIS_PASSWORD or None, db=settings.REDIS_DB,
                            socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
        await self.client.ping()
        self.limiter = RedisRateLimiter(self.client)
        self.prefix = "test-" + uuid4().hex
        self.keys = []

    def budget(self, name, count, seconds):
        result = policy(self.prefix + name, "isolated-test", count, seconds)
        self.keys.append(result[0])
        return result

    async def asyncTearDown(self):
        if self.keys:
            await self.client.delete(*self.keys)
        await self.client.aclose()

    async def test_concurrent_requests_cannot_exceed_limit(self):
        budgets = [self.budget("burst", 5, 60)]
        results = await asyncio.gather(*(self.limiter.check(budgets) for _ in range(20)), return_exceptions=True)
        self.assertEqual(sum(item is None for item in results), 5)
        self.assertEqual(sum(isinstance(item, HTTPException) and item.status_code == 429 for item in results), 15)
        self.assertEqual(await self.client.zcard(budgets[0][0]), 5)
        self.assertGreater(await self.client.pttl(budgets[0][0]), 0)

    async def test_cooldown_rejection_does_not_charge_hourly_budget(self):
        budgets = [self.budget("hour", 20, 3600), self.budget("pause", 1, 15)]
        await self.limiter.check(budgets)
        for _ in range(3):
            with self.assertRaises(HTTPException):
                await self.limiter.check(budgets)
        self.assertEqual(await self.client.zcard(budgets[0][0]), 1)
        self.assertEqual(await self.client.zcard(budgets[1][0]), 1)

    async def test_old_scores_expire_and_identity_is_independent(self):
        budget = self.budget("age", 1, 60)
        await self.limiter.check([budget])
        with self.assertRaises(HTTPException): await self.limiter.check([budget])
        clock = await self.client.time()
        now_ms = clock[0] * 1000 + clock[1] // 1000
        await self.client.delete(budget[0])
        await self.client.zadd(budget[0], {"expired": now_ms - 60001})
        await self.limiter.check([budget])
        self.assertEqual(await self.client.zcard(budget[0]), 1)
        await self.limiter.check([self.budget("other", 1, 60)])
