from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.core.security import create_access_token
from backend.database.models.user import UserProfile
from backend.database.models.achievement import UserAchievement
from tests.test_watchlist import DatabaseAPITestCase


class PublicProfilesTests(DatabaseAPITestCase):
    def test_mini_profile_has_only_public_fields_and_selected_achievements(self):
        with Session(self.engine) as db:
            db.add(UserAchievement(user_id=self.owner_id, code="email_verified", showcase_slot=1))
            db.add(UserAchievement(user_id=self.owner_id, code="first_anime"))
            db.commit()
        for headers in ({}, self.owner_headers, self.other_headers):
            result = self.client.get(f"/api/v1/profile/{self.owner_id}/mini", headers=headers)
            self.assertEqual(result.status_code, 200, result.text)
            data = result.json()
            self.assertEqual(set(data), {"profile", "achievements"})
            self.assertEqual(data["profile"]["username"], "owner")
            self.assertNotIn("email", data["profile"])
            self.assertNotIn("email_verified", data["profile"])
            self.assertNotIn("last_online", data["profile"])
            self.assertNotIn("can_write_reviews", data["profile"])
            self.assertEqual([item["code"] for item in data["achievements"]], ["email_verified"])
            self.assertNotIn("progress", data["achievements"][0])
            self.assertEqual(result.headers["cache-control"], "private, no-store")

    def test_public_profile_has_only_allowed_fields_even_for_owner(self):
        path = f"/api/v1/profile/{self.owner_id}"
        for headers in ({}, self.owner_headers, self.other_headers):
            response = self.client.get(path, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(set(response.json()), {
                "id", "username", "nickname", "avatar_url", "profile_background", "country", "bio", "created_at", "show_watchlist",
                "mini_profile_background", "profile_theme",
            })
            self.assertEqual(response.json()["username"], "owner")
            self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_closed_list_and_summary_protect_guests_and_other_accounts(self):
        for suffix in ("", "/summary"):
            path = f"/api/v1/users/{self.owner_id}/watchlist" + suffix
            for headers in ({}, self.other_headers):
                self.assertEqual(self.client.get(path, headers=headers).status_code, 403)
            self.assertEqual(self.client.get(path, headers=self.owner_headers).status_code, 200)

    def test_visibility_toggle_applies_to_list_and_summary_immediately(self):
        base = f"/api/v1/users/{self.owner_id}/watchlist"
        for visible, status in ((True, 200), (False, 403)):
            response = self.client.patch("/api/v1/profile/settings", headers=self.owner_headers,
                                        json={"show_watchlist": visible})
            self.assertEqual(response.status_code, 200, response.text)
            for headers in ({}, self.other_headers):
                for suffix in ("", "/summary"):
                    result = self.client.get(base + suffix, headers=headers)
                    self.assertEqual(result.status_code, status, result.text)
                    self.assertEqual(result.headers["cache-control"], "private, no-store")

    def test_expired_and_revoked_token_cannot_access_owner_private_list(self):
        expired = create_access_token(self.owner_id, expires_delta=timedelta(seconds=-1))
        path = f"/api/v1/users/{self.owner_id}/watchlist"
        self.assertEqual(self.client.get(path, headers={"Authorization": "Bearer " + expired}).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers=self.owner_headers).status_code, 204)
        self.assertEqual(self.client.get(path, headers=self.owner_headers).status_code, 401)

    def test_editing_cannot_target_another_user_or_grant_permissions(self):
        result = self.client.patch("/api/v1/profile/settings", headers=self.other_headers,
                                  json={"id": str(self.owner_id), "nickname": "Hacked", "show_watchlist": True})
        self.assertEqual(result.status_code, 422)
        self.assertEqual(self.client.patch(f"/api/v1/profile/{self.owner_id}", headers=self.other_headers,
                                          json={"nickname": "Hacked"}).status_code, 405)
        owner = self.client.get(f"/api/v1/profile/{self.owner_id}").json()
        self.assertIsNone(owner["nickname"])
        self.assertFalse(owner["show_watchlist"])
        self.assertEqual(self.client.patch("/api/v1/profile/settings", json={"show_watchlist": True}).status_code, 401)

    def test_nonexistent_and_inactive_profiles_and_lists_are_unavailable(self):
        with Session(self.engine) as db:
            db.get(UserProfile, self.owner_id).is_active = False
            db.commit()
        for user_id in (self.owner_id, uuid4()):
            for path in (f"/api/v1/profile/{user_id}", f"/api/v1/profile/{user_id}/mini", f"/api/v1/users/{user_id}/watchlist", f"/api/v1/users/{user_id}/watchlist/summary"):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_public_frontend_routes_are_served(self):
        for path in (f"/profile/{self.owner_id}", f"/profile/{self.owner_id}/list"):
            result = self.client.get(path)
            self.assertEqual(result.status_code, 200)
            self.assertIn('id="profile-page"', result.text)
