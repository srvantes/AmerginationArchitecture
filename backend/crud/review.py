

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Any, Dict
import datetime

from .anime import CRUDAnime
from .base import CRUDBase
from ..database.models.anime import Review
from ..database.sсhemas.anime import BaseAnime, BaseReviews, BaseGenre


class CRUDReview(CRUDAnime[BaseAnime, BaseReviews, BaseGenre]):
    def __init__(self, ):
        super().__init__(Review)

    async def get_review_by_id(self, id: int, db: AsyncSession) -> Optional[BaseReviews]:
        result = await db.execute(select(Review).where(Review.id == id))
        return result.scalar_one_or_none()

    async def write_review(self, review: BaseReviews, db: AsyncSession):
        db_review = Review(
            text=review.text,
            user_id=review.user_id,
            anime_id=review.anime_id,
            anime_title=review.anime_title,
            anime_rating=review.rating,
        )

        db.add(db_review)
        await db.commit()
        await db.refresh(db_review)
        return db_review


