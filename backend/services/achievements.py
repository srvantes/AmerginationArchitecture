from sqlalchemy import select, func, update
from fastapi import HTTPException

from backend.database.models.achievement import UserAchievement
from backend.database.models.user import User, UserProfile
from backend.database.models.anime import Review
from backend.database.models.comment import Comment, CommentLike
from backend.database.models.watchlist import WatchlistEntry

CATALOG = {
    "email_verified": ("На связи", "Подтвердить почту.", 1),
    "first_anime": ("Первая история", "Завершить первое аниме.", 1),
    "ten_anime": ("Десять историй", "Завершить 10 аниме.", 10),
    "eleven_likes": ("Голос сообщества", "Получить 11 лайков под своими комментариями.", 11),
    "first_review": ("Есть что сказать", "Опубликовать первую рецензию.", 1),
}


async def locked_profile(db, user_id):
    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id).with_for_update()
                              .execution_options(populate_existing=True))
    profile = result.scalar_one_or_none()
    if profile is None or not profile.is_active:
        raise HTTPException(404, "Пользователь не найден.")
    return profile


async def earned_rows(db, user_id):
    rows = await db.execute(select(UserAchievement).where(UserAchievement.user_id == user_id))
    return {row.code: row for row in rows.scalars().all()}


async def sync_achievements(db, user_id):
    """The caller commits awards together with its action; profile lock serializes awards."""
    await db.flush()
    profile = await locked_profile(db, user_id)
    email = await db.execute(select(User.email_verified_at).where(User.id == user_id))
    completed = await db.execute(select(func.count()).select_from(WatchlistEntry).where(
        WatchlistEntry.user_id == user_id, WatchlistEntry.status == "completed"))
    reviews = await db.execute(select(func.count()).select_from(Review).where(Review.user_id == user_id))
    likes = await db.execute(select(func.count()).select_from(CommentLike).join(Comment,
        Comment.id == CommentLike.comment_id).where(Comment.user_id == user_id, CommentLike.user_id != user_id))
    finished = completed.scalar_one()
    progress = {"email_verified": int(email.scalar_one() is not None), "first_anime": min(finished, 1),
                "ten_anime": min(finished, 10), "first_review": min(reviews.scalar_one(), 1),
                "eleven_likes": 11 if profile.can_write_reviews else min(likes.scalar_one(), 11)}
    rows = await earned_rows(db, user_id)
    for code, (_, _, target) in CATALOG.items():
        if progress[code] >= target and code not in rows:
            rows[code] = UserAchievement(user_id=user_id, code=code)
            db.add(rows[code])
    await db.flush()
    return rows, progress


def achievement_data(code, row=None):
    title, description, target = CATALOG[code]
    return {"code": code, "title": title, "description": description, "target": target,
            "awarded_at": row.awarded_at if row else None, "showcase_slot": row.showcase_slot if row else None}


async def my_achievements(db, user_id):
    rows, progress = await sync_achievements(db, user_id)
    await db.commit()
    return [{**achievement_data(code, rows.get(code)),
             "progress": target if code in rows else progress[code]}
            for code, (_, _, target) in CATALOG.items()]


async def public_showcase(db, user_id):
    # Reading someone else's showcase never awards or exposes unselected achievements.
    profile = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    profile = profile.scalar_one_or_none()
    if profile is None or not profile.is_active:
        raise HTTPException(404, "Пользователь не найден.")
    rows = await db.execute(select(UserAchievement).where(UserAchievement.user_id == user_id,
        UserAchievement.showcase_slot.is_not(None)).order_by(UserAchievement.showcase_slot))
    return [achievement_data(row.code, row) for row in rows.scalars().all()]


async def select_showcase(db, user_id, codes):
    rows, _ = await sync_achievements(db, user_id)
    if any(code not in rows for code in codes):
        raise HTTPException(400, "На витрину можно добавить только полученные достижения.")
    await db.execute(update(UserAchievement).where(UserAchievement.user_id == user_id).values(showcase_slot=None))
    await db.flush()
    for slot, code in enumerate(codes, 1):
        rows[code].showcase_slot = slot
    await db.flush()
    result = [achievement_data(code, rows[code]) for code in codes]
    await db.commit()
    return result
