import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, PngImagePlugin
from sqlalchemy.orm import Session
from starlette.staticfiles import StaticFiles

from backend.database.models.user import UserProfile
from main import app
from tests.test_watchlist import DatabaseAPITestCase, AsyncSessionAdapter


def picture(size=(500, 300), format="PNG"):
    image = Image.new("RGB", size, "navy")
    output = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Comment", "private source metadata")
    image.save(output, format=format, **({"pnginfo": metadata} if format == "PNG" else {}))
    return output.getvalue()


class ProfileEditorTests(DatabaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.folder_patch = patch("backend.services.avatars.AVATAR_DIR", self.root)
        self.folder_patch.start()
        mount = next(route for route in app.routes if getattr(route, "name", None) == "avatars")
        self.mount_patch = patch.object(mount, "app", StaticFiles(directory=self.root))
        self.mount_patch.start()

    def tearDown(self):
        self.mount_patch.stop()
        self.folder_patch.stop()
        self.directory.cleanup()
        super().tearDown()

    def upload(self, data=None, mime="image/png", headers=None):
        return self.client.post("/api/v1/profile/avatar", content=picture() if data is None else data,
                                headers={**(self.owner_headers if headers is None else headers), "Content-Type": mime})

    def test_edit_only_current_profile_and_clear_optional_fields(self):
        response = self.client.patch("/api/v1/profile/settings", headers=self.owner_headers,
                                     json={"nickname": "  Новое имя  ", "bio": "Описание", "country": "Россия"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["nickname"], "Новое имя")
        with Session(self.engine) as session:
            self.assertIsNone(session.get(UserProfile, self.other_id).nickname)
        response = self.client.patch("/api/v1/profile/settings", headers=self.owner_headers,
                                     json={"nickname": "   ", "bio": "", "country": None})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["nickname"])
        self.assertIsNone(response.json()["bio"])
        for payload in ({"nickname": "a" * 101}, {"bio": "a" * 1001}, {"country": "a" * 101},
                        {"id": str(self.other_id)}, {"is_premium": True}, {"role": "admin"}, {"status": None}):
            self.assertEqual(self.client.patch("/api/v1/profile/settings", headers=self.owner_headers, json=payload).status_code, 422)

    def test_upload_normalizes_serves_and_replaces_owned_image(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.text)
        url = response.json()["avatar_url"]
        self.assertTrue(url.startswith(f"/media/avatars/{self.owner_id}-"))
        served = self.client.get(url)
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.headers["content-type"], "image/png")
        with Image.open(io.BytesIO(served.content)) as image:
            self.assertEqual(image.size, (256, 256))
            self.assertNotIn("Comment", image.info)
        other = self.upload(headers=self.other_headers).json()["avatar_url"]
        updated = self.upload(picture(format="JPEG"), "image/jpeg")
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertNotEqual(updated.json()["avatar_url"], url)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(other).status_code, 200)

    def test_upload_rejects_invalid_type_content_size_and_dimensions(self):
        cases = [(b"<svg></svg>", "image/svg+xml", 415), (b"<script>bad</script>", "image/png", 400),
                 (b"", "image/png", 400), (b"x" * (2 * 1024 * 1024 + 1), "image/png", 413),
                 (picture((4097, 1)), "image/png", 400), (picture(format="GIF"), "image/png", 400)]
        for content, mime, status in cases:
            with self.subTest(status=status, mime=mime):
                self.assertEqual(self.upload(content, mime).status_code, status)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unauthenticated_upload_and_failed_commit_leave_no_files(self):
        self.assertEqual(self.upload(headers={}).status_code, 401)
        with patch.object(AsyncSessionAdapter, "commit", side_effect=RuntimeError("test commit failure")):
            with self.assertRaises(RuntimeError):
                self.upload()
        self.assertEqual(list(self.root.iterdir()), [])
        with Session(self.engine) as session:
            self.assertFalse((session.get(UserProfile, self.owner_id).avatar_url or "").startswith("/media/avatars/"))
