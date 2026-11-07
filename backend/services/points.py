from sqlalchemy import func, select

from backend.database.models.profile_shop import PointEvent
from backend.database.models.user import UserProfile

COMMENT_POINTS = 5
REVIEW_POINTS = 100
COMMENT_LIKE_POINTS = 10
REVIEW_LIKE_POINTS = 30


async def lock_profile(db, user_id):
    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id).with_for_update()
                              .execution_options(populate_existing=True))
    return result.scalar_one()


async def balance(db, user_id):
    result = await db.execute(select(func.coalesce(func.sum(PointEvent.delta), 0)).where(PointEvent.user_id == user_id))
    return result.scalar_one()


async def award_points(db, user_id, key, amount):
    """Record a reward in the caller's transaction with the recipient's profile locked."""
    existing = await db.execute(select(PointEvent.key).where(PointEvent.user_id == user_id, PointEvent.key == key))
    if existing.scalar_one_or_none() is None:
        db.add(PointEvent(user_id=user_id, key=key, delta=amount))
