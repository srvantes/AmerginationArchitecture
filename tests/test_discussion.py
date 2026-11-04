from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from backend.database.models.user import UserProfile
from backend.database.models.comment import Comment, CommentLike
from tests.test_watchlist import DatabaseAPITestCase


class DiscussionTests(DatabaseAPITestCase):
    comment_path = "/api/v1/comments/"
    review_path = "/api/v1/reviews/"

    def comment(self, text="Обсуждаем аниме", source="shikimori", anime="20", spoilers=False, headers=None):
        return self.client.post(self.comment_path, headers=headers or self.owner_headers, json={
            "anime_source": source, "anime_external_id": anime, "text": text, "has_spoilers": spoilers})

    def review(self, words=250, **changes):
        return {"anime_source": "shikimori", "anime_external_id": "20", "anime_title": "Наруто",
                "title": "Впечатления", "text": "содержательное-слово " * words,
                "has_spoilers": False, **changes}

    def grant(self):
        for i in range(11):
            comment = self.comment(anime=str(20 + i)).json()
            result = self.client.put(self.comment_path + comment["id"] + "/like", headers=self.other_headers)
            self.assertEqual(result.status_code, 200, result.text)
        return comment["id"]

    def test_comment_word_limits_unicode_and_punctuation(self):
        for text, status in [("слово " * 250, 201), ("слово " * 251, 422), (" \n ", 422),
                             ("... !!!", 422), ("по-моему\nинтересно", 201)]:
            self.assertEqual(self.comment(text=text).status_code, status)
        result = self.comment(spoilers=True)
        self.assertTrue(result.json()["has_spoilers"])
        self.assertEqual(self.client.post(self.comment_path, json={"anime_source": "shikimori", "anime_external_id": "20", "text": "текст"}).status_code, 401)

    def test_likes_unique_and_self_likes_forbidden(self):
        comment_id = self.comment().json()["id"]
        path = self.comment_path + comment_id + "/like"
        self.assertEqual(self.client.put(path, headers=self.owner_headers).status_code, 403)
        for _ in range(2):
            result = self.client.put(path, headers=self.other_headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["likes_count"], 1)
            self.assertTrue(result.json()["liked_by_me"])
        for _ in range(2):
            result = self.client.delete(path, headers=self.other_headers)
            self.assertEqual(result.json()["likes_count"], 0)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(CommentLike)), 0)

    def test_eleven_total_likes_unlock_permanently(self):
        ids = []
        for i in range(11):
            item = self.comment(anime=str(i + 1)).json(); ids.append(item["id"])
            self.client.put(self.comment_path + item["id"] + "/like", headers=self.other_headers)
            access = self.client.get(self.comment_path + "eligibility", headers=self.owner_headers).json()
            self.assertEqual(access["likes_received"], i + 1)
            self.assertEqual(access["can_write_reviews"], i >= 10)
        self.client.delete(self.comment_path + ids[-1] + "/like", headers=self.other_headers)
        self.client.delete(self.comment_path + ids[0], headers=self.owner_headers)
        access = self.client.get(self.comment_path + "eligibility", headers=self.owner_headers).json()
        self.assertTrue(access["can_write_reviews"])
        self.assertEqual(access["likes_received"], 9)
        with Session(self.engine) as session:
            self.assertTrue(session.get(UserProfile, self.owner_id).can_write_reviews)
        self.assertEqual(self.client.post(self.review_path, json=self.review(), headers=self.owner_headers).status_code, 201)

    def test_locked_review_and_boundaries_explicit_spoiler_choice(self):
        self.assertEqual(self.client.post(self.review_path, json=self.review(), headers=self.owner_headers).status_code, 403)
        self.grant()
        for words in (249, 1501):
            self.assertEqual(self.client.post(self.review_path, json=self.review(words), headers=self.owner_headers).status_code, 422)
        for value in (None, "true"):
            self.assertEqual(self.client.post(self.review_path, json=self.review(has_spoilers=value), headers=self.owner_headers).status_code, 422)
        data = self.review(); del data["has_spoilers"]
        self.assertEqual(self.client.post(self.review_path, json=data, headers=self.owner_headers).status_code, 422)
        result = self.client.post(self.review_path, json=self.review(1500, has_spoilers=True), headers=self.owner_headers)
        self.assertEqual(result.status_code, 201, result.text)
        self.assertTrue(result.json()["has_spoilers"])
        self.assertEqual(result.json()["author_name"], "owner")

    def test_profile_update_cannot_grant_review_access(self):
        response = self.client.patch("/api/v1/profile/settings", headers=self.owner_headers,
                                     json={"can_write_reviews": True})
        self.assertEqual(response.status_code, 422, response.text)
        profile = self.client.get("/api/v1/auth/me", headers=self.owner_headers)
        self.assertFalse(profile.json()["profile"]["can_write_reviews"])
        self.assertEqual(self.client.post(self.review_path, json=self.review(), headers=self.owner_headers).status_code, 403)

    def test_one_review_per_title_edit_and_ownership(self):
        self.grant()
        item = self.client.post(self.review_path, json=self.review(), headers=self.owner_headers).json()
        self.assertEqual(self.client.post(self.review_path, json=self.review(), headers=self.owner_headers).status_code, 409)
        path = self.review_path + item["id"]
        for method in ("patch", "delete"):
            args = {"json": {"title": "Чужая"}} if method == "patch" else {}
            self.assertEqual(getattr(self.client, method)(path, headers=self.other_headers, **args).status_code, 403)
        self.assertEqual(self.client.patch(path, json={"text": "мало слов"}, headers=self.owner_headers).status_code, 422)
        self.assertEqual(self.client.patch(path, json={"text": None}, headers=self.owner_headers).status_code, 422)
        result = self.client.patch(path, json={"title": "Новое название", "has_spoilers": True}, headers=self.owner_headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["has_spoilers"])
        self.assertEqual(result.json()["title"], "Новое название")
        self.assertEqual(self.client.delete(path, headers=self.owner_headers).status_code, 204)

    def test_comment_ownership_deletion_cascades_and_liked_view(self):
        item = self.comment().json(); path = self.comment_path + item["id"]
        self.client.put(path + "/like", headers=self.other_headers)
        params = {"anime_source": "shikimori", "anime_external_id": "20"}
        result = self.client.get(self.comment_path, params=params, headers=self.other_headers).json()
        self.assertTrue(result["items"][0]["liked_by_me"])
        self.assertFalse(self.client.get(self.comment_path, params=params).json()["items"][0]["liked_by_me"])
        self.assertEqual(self.client.patch(path, json={"text": "Чужая правка"}, headers=self.other_headers).status_code, 403)
        self.assertEqual(self.client.delete(path, headers=self.other_headers).status_code, 403)
        result = self.client.patch(path, json={"text": "Своя правка", "has_spoilers": True}, headers=self.owner_headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["likes_count"], 1)
        self.assertTrue(result.json()["has_spoilers"])
        self.assertEqual(self.client.delete(path, headers=self.owner_headers).status_code, 204)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(CommentLike)), 0)

    def test_feed_source_identity_pagination_and_anonymous_reviews(self):
        for _ in range(3): self.comment()
        self.comment(source="animego")
        params = {"anime_source": "shikimori", "anime_external_id": "20", "limit": 2}
        first = self.client.get(self.comment_path, params=params).json()
        second = self.client.get(self.comment_path, params={**params, "offset": 2}).json()
        self.assertEqual(first["total"], 3)
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(len(second["items"]), 1)
        self.assertNotIn(second["items"][0]["id"], [item["id"] for item in first["items"]])
        self.grant()
        self.client.post(self.review_path, json=self.review(), headers=self.owner_headers)
        reviews = self.client.get(self.review_path, params=params)
        self.assertEqual(reviews.status_code, 200, reviews.text)
        self.assertEqual(reviews.json()["total"], 1)
        self.assertEqual(reviews.json()["items"][0]["title"], "Впечатления")
