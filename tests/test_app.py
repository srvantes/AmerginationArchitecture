import unittest

from fastapi.testclient import TestClient

from main import app


class AppSmokeTests(unittest.TestCase):
    def test_openapi_contains_main_routes(self):
        with TestClient(app) as client:
            response = client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertIn("/api/v1/auth/register", paths)
        self.assertIn("/api/v1/anime/search", paths)
        self.assertIn("/api/v1/reviews/", paths)

    def test_protected_endpoint_requires_bearer_token(self):
        with TestClient(app) as client:
            response = client.get("/api/v1/auth/me")

        self.assertEqual(response.status_code, 401)
