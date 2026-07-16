from fastapi import HTTPException
from uuid import UUID

from fastapi.openapi.utils import status_code_ranges
from sqlalchemy import select, delete
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Any, Dict
import datetime

from .anime import CRUDAnime
from .base import CRUDBase
from ..database.models.anime import Review
from ..database.sсhemas.anime import BaseReviews, CreateReview, UpdateReview


class CRUDReview(CRUDAnime[Review, CreateReview, UpdateReview]):
    def __init__(self, ):
        super().__init__(Review)

    async def get_review_by_id(self, id: UUID, db: AsyncSession) -> Optional[BaseReviews]:
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

    async def delete_review(self, review_id: UUID, db: AsyncSession, user_id: UUID):
        result = await db.execute(select(Review).where(Review.id == review_id))
        review = result.scalar_one_or_none()

        if not review:
            return False

        if review.user_id != user_id:
            raise HTTPException(status_code=403, detail="You can only delete your own reviews")

        await db.delete(review)
        await db.commit()
        return True

    async def update_review(self, review_id: UUID, user_id: UUID, db: AsyncSession, review_data: UpdateReview):
        result = await db.execute(select(Review).where(Review.id == review_id))
        review = result.scalar_one_or_none()
        if not review:
            return False
        if review.user_id != user_id:
            raise HTTPException(status_code=403, detail="You can only update your own reviews")

        update_dict = review_data.model_dump(exclude_unset=True)

        for field, value in update_dict.items():
            setattr(review, field, value)

        await db.commit()
        await db.refresh(review)
        return review

review_db = CRUDReview()