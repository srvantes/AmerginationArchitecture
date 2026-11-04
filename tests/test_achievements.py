from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models.user import User, UserProfile
from backend.database.models.achievement import UserAchievement
from backend.services.email_verification import digest
from backend.database.models.email_verification import EmailVerification
from tests.test_watchlist import DatabaseAPITestCase


class AchievementTests(DatabaseAPITestCase):
    mine = "/api/v1/profile/me/achievements"
    showcase = mine + "/showcase"

    def achievements(self):
        result = self.client.get(self.mine, headers=self.owner_headers)
        self.assertEqual(result.status_code, 200, result.text)
        return {item["code"]: item for item in result.json()}

    def add_anime(self, number, status="completed"):
        result = self.client.post("/api/v1/users/me/watchlist", headers=self.owner_headers,
                                  json={"anime_external_id": str(number), "anime_title": "Аниме", "status": status})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def test_existing_verified_email_is_awarded_once_and_hidden_by_default(self):
        first = self.achievements()
        self.assertIsNotNone(first["email_verified"]["awarded_at"])
        self.assertEqual(len(first), 5)
        self.assertIsNone(first["first_review"]["awarded_at"])
        self.assertEqual(first["email_verified"]["awarded_at"], self.achievements()["email_verified"]["awarded_at"])
        self.assertEqual(self.client.get(f"/api/v1/profile/{self.owner_id}/achievements").json(), [])

    def test_completion_thresholds_award_during_mutation_and_are_permanent(self):
        first = self.add_anime(1)
        with Session(self.engine) as db:
            self.assertIsNotNone(db.get(UserAchievement, (self.owner_id, "first_anime")))
        for number in range(2, 10):
            self.add_anime(number)
        self.assertIsNone(self.achievements()["ten_anime"]["awarded_at"])
        self.add_anime(10)
        before = self.achievements()["ten_anime"]["awarded_at"]
        self.assertIsNotNone(before)
        path = "/api/v1/users/me/watchlist/" + first["id"]
        self.assertEqual(self.client.patch(path, headers=self.owner_headers, json={"status": "dropped"}).status_code, 200)
        self.client.delete(path, headers=self.owner_headers)
        self.assertEqual(self.achievements()["ten_anime"]["awarded_at"], before)

    def test_uncompleted_anime_does_not_count_and_selection_cannot_unlock(self):
        self.add_anime(1, "watching")
        self.assertIsNone(self.achievements()["first_anime"]["awarded_at"])
        result = self.client.put(self.showcase, headers=self.owner_headers, json={"codes": ["ten_anime"]})
        self.assertEqual(result.status_code, 400)
        for codes in (["email_verified"] * 2, ["missing"], ["email_verified", "first_anime", "ten_anime", "eleven_likes", "first_review"]):
            self.assertEqual(self.client.put(self.showcase, headers=self.owner_headers, json={"codes": codes}).status_code, 422)

    def test_showcase_order_clear_and_public_privacy(self):
        self.add_anime(1)
        selected = ["first_anime", "email_verified"]
        result = self.client.put(self.showcase, headers=self.owner_headers, json={"codes": selected})
        self.assertEqual(result.status_code, 200, result.text)
        path = f"/api/v1/profile/{self.owner_id}/achievements"
        items = self.client.get(path).json()
        self.assertEqual([item["code"] for item in items], selected)
        self.assertEqual([item["showcase_slot"] for item in items], [1, 2])
        self.assertNotIn("progress", items[0])
        # Selected badges are an explicit disclosure even while the list remains private.
        self.assertEqual(self.client.get(f"/api/v1/users/{self.owner_id}/watchlist").status_code, 403)
        result = self.client.put(self.showcase, headers=self.owner_headers, json={"codes": selected[::-1]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([item["code"] for item in result.json()], selected[::-1])
        self.assertEqual(self.client.put(self.showcase, headers=self.owner_headers, json={"codes": []}).status_code, 200)
        self.assertEqual(self.client.get(path).json(), [])

    def test_foreign_user_cannot_edit_or_discover_private_achievement_catalog(self):
        self.add_anime(1)
        result = self.client.put(self.showcase, headers=self.other_headers, json={"codes": ["first_anime"]})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.get(self.mine).status_code, 401)
        self.assertEqual(self.client.put(self.showcase, json={"codes": []}).status_code, 401)
        self.assertEqual(self.client.put(self.showcase, headers=self.owner_headers,
                                        json={"codes": [], "user_id": str(self.other_id)}).status_code, 422)
        self.assertEqual(self.client.get(f"/api/v1/profile/{self.owner_id}/achievements").json(), [])

    def test_first_review_and_likes_awarded_before_content_is_deleted(self):
        ids = []
        for number in range(11):
            item = self.client.post("/api/v1/comments/", headers=self.owner_headers,
                json={"anime_source": "shikimori", "anime_external_id": str(number), "text": "Комментарий"}).json()
            ids.append(item["id"])
            result = self.client.put("/api/v1/comments/" + item["id"] + "/like", headers=self.other_headers)
            self.assertEqual(result.status_code, 200, result.text)
        with Session(self.engine) as db:
            self.assertIsNotNone(db.get(UserAchievement, (self.owner_id, "eleven_likes")))
        result = self.client.post("/api/v1/reviews/", headers=self.owner_headers, json={
            "anime_source": "shikimori", "anime_external_id": "20", "anime_title": "Наруто", "title": "Рецензия",
            "text": "слово " * 250, "has_spoilers": False})
        self.assertEqual(result.status_code, 201, result.text)
        review_id = result.json()["id"]
        with Session(self.engine) as db:
            self.assertIsNotNone(db.get(UserAchievement, (self.owner_id, "first_review")))
        self.client.delete("/api/v1/reviews/" + review_id, headers=self.owner_headers)
        self.client.delete("/api/v1/comments/" + ids[0], headers=self.owner_headers)
        badges = self.achievements()
        self.assertIsNotNone(badges["eleven_likes"]["awarded_at"])
        self.assertIsNotNone(badges["first_review"]["awarded_at"])

    def test_unverified_email_and_inactive_profile_do_not_unlock(self):
        with Session(self.engine) as db:
            db.get(User, self.owner_id).email_verified_at = None
            db.commit()
        self.assertIsNone(self.achievements()["email_verified"]["awarded_at"])
        with Session(self.engine) as db:
            db.get(UserProfile, self.owner_id).is_active = False
            db.commit()
        self.assertEqual(self.client.get(f"/api/v1/profile/{self.owner_id}/achievements").status_code, 404)

    def test_user_delete_cascades_achievements(self):
        self.achievements()
        with Session(self.engine) as db:
            db.delete(db.get(User, self.owner_id))
            db.commit()
            self.assertEqual(db.scalars(select(UserAchievement).where(UserAchievement.user_id == self.owner_id)).all(), [])

    def test_confirmation_awards_only_after_correct_code(self):
        with Session(self.engine) as db:
            db.get(User, self.owner_id).email_verified_at = None
            db.add(EmailVerification(user_id=self.owner_id, code_digest=digest(self.owner_id, "001234"),
                                    expires_at=datetime.now(timezone.utc)+timedelta(seconds=120), attempts=0))
            db.commit()
        path = "/api/v1/auth/email/verify"
        self.assertEqual(self.client.post(path, headers=self.owner_headers, json={"code": "999999"}).status_code, 400)
        with Session(self.engine) as db:
            self.assertIsNone(db.get(UserAchievement, (self.owner_id, "email_verified")))
        self.assertEqual(self.client.post(path, headers=self.owner_headers, json={"code": "001234"}).status_code, 200)
        with Session(self.engine) as db:
            self.assertIsNotNone(db.get(UserAchievement, (self.owner_id, "email_verified")))
