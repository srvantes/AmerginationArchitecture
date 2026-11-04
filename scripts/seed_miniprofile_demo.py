"""Create one clearly marked local demo account and one One Piece comment; safe to rerun."""
import asyncio
import secrets
from datetime import datetime, timezone

from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal, engine
from backend.core.password import get_password_hash
from backend.database.models.user import User, UserProfile
from backend.database.models.comment import Comment
from backend.database.models.achievement import UserAchievement
from backend.services.achievements import select_showcase

USERNAME = "mini_profile_demo"
EMAIL = "mini-profile-demo@example.com"
COMMENT = "Первая серия. Тестовый комментарий для проверки мини-профиля: наведите на мой ник или нажмите на него с телефона."


async def main():
    assert settings.POSTGRES_HOST in {"localhost", "127.0.0.1", "::1"}, "Local development database only"
    try:
        async with AsyncSessionLocal() as db:
            user = (await db.execute(select(User).where(User.username == USERNAME))).scalar_one_or_none()
            if user is None:
                user = User(username=USERNAME, email=EMAIL, hashed_password=get_password_hash(secrets.token_urlsafe(40)),
                            email_verified_at=datetime.now(timezone.utc),
                            profile=UserProfile(nickname="Тестовый зритель", country="Россия", status="offline",
                                bio="Тестовый аккаунт для проверки мини-профиля и витрины достижений.", show_watchlist=False))
                db.add(user)
                await db.flush()
            elif user.email != EMAIL:
                raise RuntimeError("Demo username belongs to a different account; no changes made")
            comment = (await db.execute(select(Comment).where(Comment.user_id == user.id,
                Comment.anime_source == "shikimori", Comment.anime_external_id == "21", Comment.text == COMMENT))).scalar_one_or_none()
            if comment is None:
                comment = Comment(user_id=user.id, anime_source="shikimori", anime_external_id="21", text=COMMENT)
                db.add(comment)
            selected = (await db.execute(select(UserAchievement).where(UserAchievement.user_id == user.id,
                UserAchievement.showcase_slot.is_not(None)))).scalars().all()
            if not selected:
                await select_showcase(db, user.id, ["email_verified"])
            else:
                await db.commit()
            print("Demo username:", USERNAME)
            print("Demo profile: http://127.0.0.1:8080/profile/" + str(user.id))
            print("One Piece: http://127.0.0.1:8080/anime/shikimori/21#comments-panel")
            print("Comment ID:", comment.id)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
