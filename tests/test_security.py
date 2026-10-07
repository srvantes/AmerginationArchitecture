import unittest
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException

from backend.core.security import (
    Permissions,
    create_access_token,
    decode_access_token,
    require_permission,
)
from backend.services.shikimori_client import _validate_shikimori_link


class TokenTests(unittest.TestCase):
    def test_access_token_roundtrip(self):
        user_id = uuid4()
        payload = decode_access_token(create_access_token(user_id))
        self.assertEqual(payload["sub"], str(user_id))
        self.assertEqual(payload["type"], "access")

    def test_expired_token_is_rejected(self):
        token = create_access_token(uuid4(), timedelta(seconds=-1))
        with self.assertRaises(HTTPException) as raised:
            decode_access_token(token)
        self.assertEqual(raised.exception.status_code, 401)

    def test_tampered_token_is_rejected(self):
        token = create_access_token(uuid4()) + "x"
        with self.assertRaises(HTTPException) as raised:
            decode_access_token(token)
        self.assertEqual(raised.exception.status_code, 401)


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_cannot_manage_system(self):
        dependency = require_permission(Permissions.MANAGE_SYSTEM)
        user = SimpleNamespace(profile=SimpleNamespace(role="user"))
        with self.assertRaises(HTTPException) as raised:
            await dependency(user=user)
        self.assertEqual(raised.exception.status_code, 403)

    async def test_admin_can_manage_system(self):
        dependency = require_permission(Permissions.MANAGE_SYSTEM)
        user = SimpleNamespace(profile=SimpleNamespace(role="admin"))
        self.assertIs(await dependency(user=user), user)


class ShikimoriUrlTests(unittest.TestCase):
    def test_valid_url_is_accepted(self):
        _validate_shikimori_link("https://shikimori.one/animes/20-naruto")

    def test_local_url_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            _validate_shikimori_link("http://127.0.0.1/animes/20-test")
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
