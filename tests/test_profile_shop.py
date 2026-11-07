import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from sqlalchemy.orm import Session

from backend.database.models.profile_shop import ProfileShopItem
from backend.database.models.user import UserProfile
from tests.test_watchlist import DatabaseAPITestCase


class ProfileShopTests(DatabaseAPITestCase):
    shop = "/api/v1/profile/shop"
    anime = {"anime_source": "shikimori", "anime_external_id": "20"}

    def points(self, headers=None):
        response = self.client.get(self.shop, headers=headers or self.owner_headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["balance"]

    def test_rewards_switching_votes_and_purchasing_are_idempotent(self):
        comment = self.client.post("/api/v1/comments/", headers=self.owner_headers,
                                   json={**self.anime, "text": "Комментарий"}).json()
        self.assertEqual(self.points(), 5)
        with Session(self.engine) as db:
            db.get(UserProfile, self.owner_id).can_write_reviews = True
            db.commit()
        review_data = {**self.anime, "anime_title": "Наруто", "title": "Рецензия", "text": "слово " * 250,
                       "has_spoilers": False}
        review = self.client.post("/api/v1/reviews/", headers=self.owner_headers, json=review_data).json()
        self.assertEqual(self.points(), 105)
        for kind, item in (("comments", comment), ("reviews", review)):
            path = f"/api/v1/{kind}/{item['id']}/"
            self.assertEqual(self.client.put(path + "dislike", headers=self.owner_headers).status_code, 403)
            for reaction in ("like", "dislike", "like", "like"):
                result = self.client.put(path + reaction, headers=self.other_headers)
                self.assertEqual(result.status_code, 200, result.text)
                expected_like = reaction == "like"
                self.assertEqual(result.json()["likes_count"], int(expected_like))
                self.assertEqual(result.json()["dislikes_count"], int(not expected_like))
                self.assertEqual(result.json()["liked_by_me"], expected_like)
                self.assertEqual(result.json()["disliked_by_me"], not expected_like)
            self.assertTrue(self.client.delete(path + "dislike", headers=self.other_headers).json()["liked_by_me"])
            self.assertEqual(self.client.delete(path + "like", headers=self.other_headers).json()["likes_count"], 0)
        self.assertEqual(self.points(), 145)
        self.assertEqual(self.points(self.other_headers), 0)

        equip = {"kind": "profile_theme", "item_id": "aurora"}
        self.assertEqual(self.client.get(self.shop).status_code, 401)
        self.assertEqual(self.client.put(self.shop + "/equip", headers=self.owner_headers, json=equip).status_code, 403)
        self.assertEqual(self.client.post(self.shop + "/twilight/buy", headers=self.owner_headers).status_code, 409)
        for _ in range(2):
            purchase = self.client.post(self.shop + "/aurora/buy", headers=self.owner_headers)
            self.assertEqual(purchase.status_code, 200, purchase.text)
            self.assertEqual(purchase.json()["balance"], 45)
        self.assertEqual(self.client.put(self.shop + "/equip", headers=self.other_headers, json=equip).status_code, 403)
        self.assertEqual(self.client.put(self.shop + "/equip", headers=self.owner_headers, json=equip).status_code, 200)
        public = self.client.get(f"/api/v1/profile/{self.owner_id}").json()
        self.assertEqual(public["profile_theme"], "aurora")
        self.assertNotIn("balance", public)

        self.assertEqual(self.client.delete(f"/api/v1/reviews/{review['id']}", headers=self.owner_headers).status_code, 204)
        again = self.client.post("/api/v1/reviews/", headers=self.owner_headers, json=review_data)
        self.assertEqual(again.status_code, 201, again.text)
        self.client.put(f"/api/v1/reviews/{again.json()['id']}/like", headers=self.other_headers)
        self.assertEqual(self.points(), 45)

    def test_custom_backgrounds_validate_replace_and_clear_independently(self):
        image = io.BytesIO()
        Image.new("RGB", (64, 48), "green").save(image, format="PNG")
        headers = {**self.owner_headers, "Content-Type": "image/png"}
        main = "/api/v1/profile/background/profile_background"
        mini = "/api/v1/profile/background/mini_profile_background"
        with TemporaryDirectory() as folder, patch("backend.services.avatars.AVATAR_DIR", Path(folder)):
            self.assertEqual(self.client.put(main, headers=headers, content=b"invalid").status_code, 400)
            self.assertEqual(self.client.put(main, headers=headers, content=b"x" * (2 * 1024**2 + 1)).status_code, 413)
            first = self.client.put(main, headers=headers, content=image.getvalue())
            self.assertEqual(first.status_code, 200, first.text)
            main_file = Path(folder) / first.json()["profile_background"].split("/")[-1]
            self.assertTrue(main_file.is_file())
            second = self.client.put(mini, headers=headers, content=image.getvalue())
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()["profile_background"], first.json()["profile_background"])
            mini_file = Path(folder) / second.json()["mini_profile_background"].split("/")[-1]
            self.assertTrue(mini_file.is_file())
            reset = self.client.put(self.shop + "/equip", headers=self.owner_headers,
                                    json={"kind": "profile_background", "item_id": None})
            self.assertEqual(reset.status_code, 200, reset.text)
            self.assertIsNone(reset.json()["profile_background"])
            self.assertFalse(main_file.exists())
            self.assertTrue(mini_file.exists())

    def test_animated_shop_assets_need_a_file_and_can_be_equipped(self):
        with Session(self.engine) as db:
            db.add(ProfileShopItem(id="stars", kind="mini_profile_background", name="Звёзды", price=0, asset="shop-stars.gif"))
            db.commit()
        purchase = self.shop + "/stars/buy"
        with TemporaryDirectory() as folder, patch("backend.services.avatars.AVATAR_DIR", Path(folder)):
            self.assertEqual(self.client.post(purchase, headers=self.owner_headers).status_code, 404)
            Image.new("RGB", (8, 8), "blue").save(Path(folder) / "shop-stars.gif", save_all=True,
                                                  append_images=[Image.new("RGB", (8, 8), "red")], duration=100, loop=0)
            self.assertEqual(self.client.post(purchase, headers=self.owner_headers).status_code, 200)
            equipped = self.client.put(self.shop + "/equip", headers=self.owner_headers,
                                       json={"kind": "mini_profile_background", "item_id": "stars"})
            self.assertEqual(equipped.status_code, 200, equipped.text)
            self.assertEqual(equipped.json()["mini_profile_background"], "/media/avatars/shop-stars.gif")
