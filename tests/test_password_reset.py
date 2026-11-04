from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from sqlalchemy.orm import Session
from redis.exceptions import RedisError
import jwt

from backend.core.config import settings
from backend.core.security import create_access_token
from backend.core.password import verify_password
from backend.database.models.user import User, UserProfile
from backend.database.models.password_reset import PasswordReset
from backend.services import password_reset as service
from tests.test_watchlist import DatabaseAPITestCase


class PasswordResetTests(DatabaseAPITestCase):
    path = "/api/v1/auth/password/"

    def request(self, email="owner@example.com", code=1234):
        with patch.object(service.secrets, "randbelow", return_value=code):
            return self.client.post(self.path + "request", json={"email": email})

    def verify(self, code="001234", email="owner@example.com"):
        return self.client.post(self.path + "verify", json={"email": email, "code": code})

    def finish(self, token, password="new-test-password-456"):
        return self.client.post(self.path + "reset", json={"reset_token": token, "new_password": password})

    def test_existing_unknown_inactive_and_unverified_requests_are_identical(self):
        with patch.object(service, "send_password_reset_email", AsyncMock()) as send:
            known = self.request()
            unknown = self.request("unknown@example.com")
            with Session(self.engine) as db:
                db.get(UserProfile, self.other_id).is_active = False
                db.commit()
            blocked = self.request("other@example.com")
            with Session(self.engine) as db:
                db.get(UserProfile, self.other_id).is_active = True
                db.get(User, self.other_id).email_verified_at = None
                db.commit()
            pending = self.request("other@example.com")
        self.assertEqual(known.status_code, 200, known.text)
        for result in (unknown, blocked, pending):
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json(), known.json())
        send.assert_awaited_once_with("owner@example.com", "001234")
        with Session(self.engine) as db:
            self.assertEqual(db.query(PasswordReset).count(), 1)

    def test_reset_changes_password_and_revokes_all_old_sessions_even_without_redis(self):
        second_token = create_access_token(self.owner_id)
        legacy = jwt.decode(second_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]); del legacy["v"]
        legacy_token = jwt.encode(legacy, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        self.assertEqual(self.request().status_code, 200)
        result = self.verify(); self.assertEqual(result.status_code, 200, result.text)
        ticket = result.json()["reset_token"]
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Authorization":"Bearer " + ticket}).status_code, 401)
        result = self.finish(ticket); self.assertEqual(result.status_code, 200, result.text)
        with Session(self.engine) as db:
            user = db.get(User, self.owner_id)
            self.assertEqual(user.auth_version, 1)
            self.assertTrue(verify_password("new-test-password-456", user.hashed_password))
            self.assertIsNone(db.get(PasswordReset, self.owner_id))
        self.redis.exists.side_effect = RedisError("offline")
        for headers in [self.owner_headers, {"Authorization":"Bearer " + second_token}, {"Authorization":"Bearer " + legacy_token}]:
            self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.other_headers).status_code, 200)
        old = self.client.post("/api/v1/auth/login", json={"username":"owner", "password":"test-password-123"})
        self.assertEqual(old.status_code, 401)
        new = self.client.post("/api/v1/auth/login", json={"username":"owner", "password":"new-test-password-456"})
        self.assertEqual(new.status_code, 200, new.text)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Authorization":"Bearer " + new.json()["access_token"]}).status_code, 200)

    def test_codes_and_tickets_are_once_only_and_bound_to_account(self):
        self.request()
        self.assertEqual(self.verify(email="other@example.com").status_code, 400)
        ticket = self.verify().json()["reset_token"]
        self.assertEqual(self.verify().status_code, 400)
        self.assertEqual(self.finish(ticket).status_code, 200)
        self.assertEqual(self.finish(ticket).status_code, 400)
        with Session(self.engine) as db:
            self.assertTrue(verify_password("test-password-123", db.get(User, self.other_id).hashed_password))

    def test_five_failed_attempts_do_not_allow_correct_code_and_new_code_resets_attempts(self):
        start = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        with patch.object(service, "utc_now", return_value=start):
            self.request()
            for _ in range(5): self.assertEqual(self.verify("111111").status_code, 400)
            self.assertEqual(self.verify().status_code, 400)
            self.request(code=2222)
            with Session(self.engine) as db:
                self.assertEqual(db.get(PasswordReset, self.owner_id).attempts, 5)
        with patch.object(service, "utc_now", return_value=start + timedelta(seconds=120)):
            self.request(code=2222)
            self.assertEqual(self.verify("002222").status_code, 200)

    def test_code_expires_at_120_seconds_and_grant_at_300_seconds(self):
        start = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        with patch.object(service, "utc_now", return_value=start): self.request()
        with patch.object(service, "utc_now", return_value=start + timedelta(seconds=120)):
            self.assertEqual(self.verify().status_code, 400)
            self.request(code=2222)
            ticket = self.verify("002222").json()["reset_token"]
        with patch.object(service, "utc_now", return_value=start + timedelta(seconds=420)):
            self.assertEqual(self.finish(ticket).status_code, 400)
        with Session(self.engine) as db:
            self.assertTrue(verify_password("test-password-123", db.get(User, self.owner_id).hashed_password))

    def test_new_request_invalidates_old_grant_and_stores_no_plaintext_code_or_token(self):
        start = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        with patch.object(service, "utc_now", return_value=start):
            self.request(); ticket = self.verify().json()["reset_token"]
        with Session(self.engine) as db:
            state = db.get(PasswordReset, self.owner_id)
            self.assertEqual(state.code_digest, service.digest(str(self.owner_id), "001234"))
            self.assertEqual(state.grant_digest, service.digest("grant", ticket))
            self.assertNotEqual(state.grant_digest, ticket)
        with patch.object(service, "utc_now", return_value=start + timedelta(seconds=120)):
            self.request(code=2222)
            self.assertEqual(self.finish(ticket).status_code, 400)

    def test_malformed_codes_passwords_and_unknown_account_responses(self):
        self.request()
        for code in (123456, "12345", "abcdef", "１２３４５６"):
            self.assertEqual(self.verify(code).status_code, 422)
        self.assertEqual(self.verify("111111").json(), self.verify("111111", "unknown@example.com").json())
        ticket = self.verify().json()["reset_token"]
        for password in ("short", "a" * 129): self.assertEqual(self.finish(ticket, password).status_code, 422)
        self.assertEqual(self.finish(ticket).status_code, 200)

    def test_delivery_failure_does_not_disclose_account(self):
        from fastapi import HTTPException
        with patch.object(service, "send_password_reset_email", AsyncMock(side_effect=HTTPException(503, "SMTP unavailable"))):
            self.assertEqual(self.request().json(), self.request("unknown@example.com").json())
