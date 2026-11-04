import unittest

from pydantic import ValidationError

from backend.core.config import Settings


class KodikSiteConfigTests(unittest.TestCase):
    def configured(self, origin):
        return Settings(_env_file=None, SECRET_KEY="test-secret-key-at-least-32-characters", KODIK_SITE_URL=origin)

    def test_local_or_production_site_origin(self):
        self.assertEqual(self.configured("http://127.0.0.1:8080/").KODIK_SITE_URL, "http://127.0.0.1:8080")
        self.assertEqual(self.configured("https://anime.example").KODIK_SITE_URL, "https://anime.example")

    def test_origin_cannot_leak_credentials_or_reference_an_unrelated_page(self):
        for value in ["https://user:password@anime.example", "https://anime.example/other-page",
                      "https://anime.example?token=private", "https://anime.example#fragment",
                      "file:///private", "http://anime.example:99999", "https://anime.example\n"]:
            with self.subTest(origin=value), self.assertRaises(ValidationError):
                self.configured(value)
