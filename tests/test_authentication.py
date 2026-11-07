"""Authentication routes against real SQL in an isolated test database."""
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.core.password import verify_password
from backend.core.security import WEB_SESSION_COOKIE, create_access_token, decode_access_token
from backend.crud.user import crud_user
from backend.database.models.user import User, UserProfile
from tests.test_watchlist import DatabaseAPITestCase


class AuthenticationTests(DatabaseAPITestCase):
    payload = {"username": "newuser", "email": "newuser@example.com", "password": "test-password-123"}

    def register(self, **changes):
        return self.client.post("/api/v1/auth/register", json={**self.payload, **changes})

    def test_browser_cookie_renews_only_live_sessions_and_logout_revokes(self):
        auth = "/api/v1/auth/"
        headers = {"X-Amergination-Client": "web"}
        data = {"username": "owner", "password": self.payload["password"]}
        self.redis.expire.side_effect = lambda key, ttl: key in self.revoked
        self.redis.delete.side_effect = self.revoked.discard
        response = self.client.post(auth + "login", headers=headers, json=data)
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])
        token = self.client.cookies.get(WEB_SESSION_COOKIE)
        key = "web-session:" + decode_access_token(token)["jti"]
        self.redis.setex.assert_awaited_with(key, 3600, "1")
        self.assertEqual(self.client.get(auth + "me", headers=headers).status_code, 200)
        self.assert_denied(self.client.get(auth + "me"))
        self.assert_denied(self.client.get(auth + "me", headers={**headers, "X-Amergination-Account": str(self.other_id)}))
        self.assertEqual(self.client.post(auth + "session", headers=headers).status_code, 204)
        self.redis.expire.assert_awaited_once_with(key, 3600)
        self.revoked.discard(key)
        self.assert_denied(self.client.post(auth + "session", headers=headers))
        self.assertNotIn(key, self.revoked)

        self.assertEqual(self.client.post(auth + "login", headers=headers, json=data).status_code, 204)
        token = self.client.cookies.get(WEB_SESSION_COOKIE)
        self.assertEqual(self.client.post(auth + "logout", headers=headers).status_code, 204)
        self.assertIsNone(self.client.cookies.get(WEB_SESSION_COOKIE))
        self.assert_denied(self.client.get(auth + "me", headers={"Authorization": "Bearer " + token}))

    def assert_user_counts(self, count=2):
        with Session(self.engine) as session:
            self.assertEqual(session.query(User).count(), count)
            self.assertEqual(session.query(UserProfile).count(), count)

    def assert_denied(self, response):
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.headers.get("www-authenticate"), "Bearer")
        self.assertNotIn("access_token", response.json())

    def test_registration_creates_user_profile_and_hashes_password(self):
        response = self.register()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(set(response.json()), {"id", "username", "email", "email_verified"})
        with Session(self.engine) as session:
            user = session.get(User, UUID(response.json()["id"]))
            self.assertIsNotNone(user.profile)
            self.assertEqual(user.profile.role, "user")
            self.assertTrue(user.profile.is_active)
            self.assertNotEqual(user.hashed_password, self.payload["password"])
            self.assertTrue(verify_password(self.payload["password"], user.hashed_password))
        self.assert_user_counts(3)

    def test_duplicate_email_rejected_without_extra_records(self):
        response = self.register(email="owner@example.com")
        self.assertEqual(response.status_code, 409, response.text)
        self.assert_user_counts()

    def test_duplicate_username_rejected_without_extra_records(self):
        response = self.register(username="owner")
        self.assertEqual(response.status_code, 409, response.text)
        self.assert_user_counts()

    def test_database_unique_constraint_handles_duplicate_after_prechecks(self):
        # Simulate both prechecks missing an account registered concurrently.
        with patch.object(crud_user, "get_by_email", AsyncMock(return_value=None)), \
             patch.object(crud_user, "get_by_username", AsyncMock(return_value=None)):
            response = self.register(username="owner", email="owner@example.com")
        self.assertEqual(response.status_code, 409, response.text)
        self.assert_user_counts()
        self.assertEqual(self.register().status_code, 201)

    def test_invalid_registration_data_does_not_create_records(self):
        invalid = [
            {"username": ""}, {"username": "ab"}, {"username": "x" * 41},
            {"username": "   "}, {"username": None},
            {"email": "not-an-email"}, {"email": None},
            {"email": "a" * 64 + "@" + "b" * 40 + ".com"},
            {"password": "short"}, {"password": "x" * 129}, {"password": None},
        ]
        for changes in invalid:
            with self.subTest(fields=list(changes)):
                response = self.register(**changes)
                self.assertEqual(response.status_code, 422, response.text)
                self.assert_user_counts()
        for field in self.payload:
            with self.subTest(missing=field):
                payload = {key: value for key, value in self.payload.items() if key != field}
                response = self.client.post("/api/v1/auth/register", json=payload)
                self.assertEqual(response.status_code, 422)
                self.assert_user_counts()

    def test_profile_integrity_failure_rolls_back_flushed_user(self):
        attempted_users = []

        def fail_profile_insert(mapper, connection, profile):
            attempted_users.append(profile.id)
            # Force a real database constraint failure after the user's INSERT.
            profile.id = self.owner_id

        event.listen(UserProfile, "before_insert", fail_profile_insert)
        try:
            response = self.register()
        finally:
            event.remove(UserProfile, "before_insert", fail_profile_insert)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(len(attempted_users), 1)
        with Session(self.engine) as session:
            self.assertIsNone(session.get(User, attempted_users[0]))
            self.assertIsNone(session.get(UserProfile, attempted_users[0]))
        self.assert_user_counts()
        self.assertEqual(self.register().status_code, 201)

    def test_unexpected_profile_failure_rolls_back_flushed_user(self):
        def fail_profile_insert(mapper, connection, profile):
            raise RuntimeError("Simulated profile creation failure")

        event.listen(UserProfile, "before_insert", fail_profile_insert)
        try:
            with self.assertRaisesRegex(RuntimeError, "Simulated profile"):
                self.register()
        finally:
            event.remove(UserProfile, "before_insert", fail_profile_insert)
        self.assert_user_counts()
        self.assertEqual(self.register().status_code, 201)

    def test_login_accepts_username_and_email(self):
        for login in ["owner", "owner@example.com"]:
            response = self.client.post("/api/v1/auth/login", json={
                "username": login, "password": "test-password-123",
            })
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["token_type"], "bearer")
            me = self.client.get("/api/v1/auth/me", headers={
                "Authorization": "Bearer " + response.json()["access_token"],
            })
            self.assertEqual(me.status_code, 200)
            self.assertEqual(me.json()["id"], str(self.owner_id))
            self.assertNotIn("hashed_password", me.json())

    def test_wrong_password_and_missing_user_have_same_response(self):
        responses = [
            self.client.post("/api/v1/auth/login", json={"username": login, "password": password})
            for login, password in [
                ("owner", "wrong-password-123"), ("missing", "test-password-123"),
            ]
        ]
        for response in responses:
            self.assert_denied(response)
        self.assertEqual(responses[0].json(), responses[1].json())

    def test_blocked_user_cannot_login_or_use_existing_token(self):
        with Session(self.engine) as session:
            session.get(UserProfile, self.owner_id).is_active = False
            session.commit()
        response = self.client.post("/api/v1/auth/login", json={
            "username": "owner", "password": "test-password-123",
        })
        self.assert_denied(response)
        self.assert_denied(self.client.get("/api/v1/auth/me", headers=self.owner_headers))

    def test_user_without_profile_cannot_login(self):
        with Session(self.engine) as session:
            session.delete(session.get(UserProfile, self.owner_id))
            session.commit()
        self.assert_denied(self.client.post("/api/v1/auth/login", json={
            "username": "owner", "password": "test-password-123",
        }))
        self.assert_denied(self.client.get("/api/v1/auth/me", headers=self.owner_headers))

    def test_token_for_missing_user_is_rejected(self):
        headers = {"Authorization": "Bearer " + create_access_token(uuid4())}
        self.assert_denied(self.client.get("/api/v1/auth/me", headers=headers))

    def test_registration_cannot_assign_administrator_role(self):
        response = self.register(role="admin", is_active=False)
        self.assertEqual(response.status_code, 201, response.text)
        with Session(self.engine) as session:
            profile = session.get(UserProfile, UUID(response.json()["id"]))
            self.assertEqual(profile.role, "user")
            self.assertTrue(profile.is_active)
