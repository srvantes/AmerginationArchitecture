from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID
from sqlalchemy.orm import Session
from pydantic import SecretStr
from fastapi import HTTPException
import unittest

from backend.database.models.user import User
from backend.database.models.email_verification import EmailVerification
from backend.services import email_verification as service, mailer
from tests.test_watchlist import DatabaseAPITestCase


class EmailVerificationTests(DatabaseAPITestCase):
    def pending(self):
        with patch.object(service, "secrets") as secret:
            secret.randbelow.return_value = 1234
            response = self.client.post("/api/v1/auth/register", json={"username": "pending", "email": "pending@example.com", "password": "test-password-123"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertFalse(response.json()["email_verified"])
        user_id = UUID(response.json()["id"])
        login = self.client.post("/api/v1/auth/login", json={"username": "pending", "password": "test-password-123"})
        return user_id, {"Authorization": "Bearer " + login.json()["access_token"]}

    def verify(self, headers, code):
        return self.client.post("/api/v1/auth/email/verify", headers=headers, json={"code": code})

    def test_registration_sends_six_digits_stores_only_digest_and_exact_lifetime(self):
        start = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        with patch.object(service, "utc_now", return_value=start), \
             patch.object(service, "send_verification_email", AsyncMock()) as send:
            user_id, headers = self.pending()
            status = self.client.get("/api/v1/auth/email/status", headers=headers).json()
        send.assert_awaited_once_with("pending@example.com", "001234")
        self.assertEqual(status["expires_in_seconds"], 120)
        self.assertEqual(status["resend_after_seconds"], 120)
        with Session(self.engine) as db:
            state = db.get(EmailVerification, user_id)
            self.assertEqual(state.code_digest, service.digest(user_id, "001234"))
            self.assertNotIn("001234", state.code_digest)
            self.assertEqual(service.aware(state.expires_at), start + timedelta(seconds=120))

    def test_pending_user_can_login_but_cannot_comment_like_or_review(self):
        _, headers = self.pending()
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 200)
        result = self.client.post("/api/v1/comments/", headers=headers, json={"anime_source": "shikimori", "anime_external_id": "20", "text": "Комментарий"})
        self.assertEqual(result.status_code, 403, result.text)
        result = self.client.put("/api/v1/comments/00000000-0000-0000-0000-000000000001/like", headers=headers)
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.verify(headers, "001234").status_code, 200)
        self.assertTrue(self.client.get("/api/v1/auth/me", headers=headers).json()["email_verified"])
        result = self.client.post("/api/v1/comments/", headers=headers, json={"anime_source": "shikimori", "anime_external_id": "20", "text": "Комментарий"})
        self.assertEqual(result.status_code, 201, result.text)

    def test_confirmation_is_one_time_and_another_user_cannot_use_code(self):
        user_id, headers = self.pending()
        self.assertEqual(self.verify(self.other_headers, "001234").status_code, 409)
        self.assertEqual(self.verify(headers, "001234").status_code, 200)
        self.assertEqual(self.verify(headers, "001234").status_code, 409)
        with Session(self.engine) as db:
            self.assertIsNone(db.get(EmailVerification, user_id))

    def test_code_expired_at_two_minutes_and_resend_is_allowed_then(self):
        start = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        with patch.object(service, "utc_now", return_value=start): user_id, headers = self.pending()
        with patch.object(service, "utc_now", return_value=start + timedelta(seconds=119)):
            result = self.client.post("/api/v1/auth/email/resend", headers=headers)
            self.assertEqual(result.status_code, 429)
            self.assertEqual(result.headers["Retry-After"], "1")
        with patch.object(service, "utc_now", return_value=start + timedelta(seconds=120)), \
             patch.object(service.secrets, "randbelow", return_value=5678):
            self.assertEqual(self.verify(headers, "001234").status_code, 400)
            self.assertEqual(self.client.post("/api/v1/auth/email/resend", headers=headers).status_code, 200)
            self.assertEqual(self.verify(headers, "001234").status_code, 400)
            self.assertEqual(self.verify(headers, "005678").status_code, 200)

    def test_five_wrong_attempts_lock_code_and_do_not_allow_early_resend(self):
        user_id, headers = self.pending()
        for i in range(5):
            result = self.verify(headers, "111111")
            self.assertEqual(result.status_code, 400 if i < 4 else 429)
        self.assertEqual(self.verify(headers, "001234").status_code, 429)
        self.assertEqual(self.client.post("/api/v1/auth/email/resend", headers=headers).status_code, 429)
        self.assertEqual(self.client.get("/api/v1/auth/email/status", headers=headers).json()["attempts_remaining"], 0)
        with Session(self.engine) as db:
            expiry = service.aware(db.get(EmailVerification, user_id).expires_at)
        with patch.object(service, "utc_now", return_value=expiry), \
             patch.object(service.secrets, "randbelow", return_value=5678):
            self.assertEqual(self.client.post("/api/v1/auth/email/resend", headers=headers).status_code, 200)
            self.assertEqual(self.client.get("/api/v1/auth/email/status", headers=headers).json()["attempts_remaining"], 5)
            self.assertEqual(self.verify(headers, "005678").status_code, 200)

    def test_invalid_formats_unauthenticated_calls_and_privilege_injection(self):
        _, headers = self.pending()
        for code in (123456, "12345", "1234567", "１２３４５６", "abcdef"):
            self.assertEqual(self.verify(headers, code).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/auth/email/verify", json={"code": "001234"}).status_code, 401)
        result = self.client.patch("/api/v1/profile/settings", headers=headers, json={"email_verified": True, "email_verified_at": "2026-10-13"})
        self.assertEqual(result.status_code, 422)
        self.assertFalse(self.client.get("/api/v1/auth/me", headers=headers).json()["email_verified"])

    def test_smtp_failure_rolls_back_registration_and_does_not_create_code(self):
        with patch.object(service, "send_verification_email", AsyncMock(side_effect=HTTPException(503, "SMTP unavailable"))):
            result = self.client.post("/api/v1/auth/register", json={"username": "pending", "email": "pending@example.com", "password": "test-password-123"})
        self.assertEqual(result.status_code, 503)
        with Session(self.engine) as db:
            self.assertEqual(db.query(User).count(), 2)
            self.assertEqual(db.query(EmailVerification).count(), 0)

    def test_email_case_cannot_create_duplicate_account(self):
        result = self.client.post("/api/v1/auth/register", json={"username": "duplicate", "email": "OWNER@EXAMPLE.COM", "password": "test-password-123"})
        self.assertEqual(result.status_code, 409)


class MailerTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_credentials_never_pretends_to_send_email(self):
        with patch.object(mailer.settings, "SMTP_PASSWORD", None):
            with self.assertRaises(HTTPException) as caught:
                await mailer.send_verification_email("recipient@example.com", "000123")
        self.assertEqual(caught.exception.status_code, 503)

    async def test_gmail_uses_tls_and_message_with_code(self):
        with patch.object(mailer.settings, "SMTP_USERNAME", "sender@gmail.com"), \
             patch.object(mailer.settings, "SMTP_FROM_EMAIL", "sender@gmail.com"), \
             patch.object(mailer.settings, "SMTP_PASSWORD", SecretStr("abcd efgh ijkl mnop")), \
             patch.object(mailer.smtplib, "SMTP_SSL") as transport:
            await mailer.send_verification_email("recipient@example.com", "000123")
        transport.assert_called_once()
        smtp = transport.return_value.__enter__.return_value
        smtp.login.assert_called_once_with("sender@gmail.com", "abcdefghijklmnop")
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "recipient@example.com")
        self.assertIn("000123", message.get_content())
        self.assertIn("2 минуты", message.get_content())
