from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .base import CRUDBase
from ..database.models.anime import Review
from ..database.sсhemas.anime import ReviewCreate, ReviewUpdate


class CRUDReview(CRUDBase[Review, ReviewCreate, ReviewUpdate]):
    def __init__(self):
        super().__init__(Review)

    async def get_review_by_id(self, db: AsyncSession, review_id: UUID) -> Review | None:
        result = await db.execute(select(Review).where(Review.id == review_id))
        return result.scalar_one_or_none()

    async def write_review(
        self,
        db: AsyncSession,
        user_id: UUID,
        review_data: ReviewCreate,
    ) -> Review:
        review = Review(
            user_id=user_id,
            anime_source=review_data.anime_source,
            anime_external_id=review_data.anime_external_id,
            anime_title=review_data.anime_title,
            text=review_data.text,
            anime_rating=review_data.rating,
        )
        db.add(review)
        await db.commit()
        await db.refresh(review)
        return review

    async def delete_review(self, db: AsyncSession, review_id: UUID, user_id: UUID) -> bool:
        review = await self.get_review_by_id(db, review_id)
        if review is None:
            return False
        if review.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own reviews",
            )
        await db.delete(review)
        await db.commit()
        return True

    async def update_review(
        self,
        db: AsyncSession,
        review_id: UUID,
        user_id: UUID,
        review_data: ReviewUpdate,
    ) -> Review | None:
        review = await self.get_review_by_id(db, review_id)
        if review is None:
            return None
        if review.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only update your own reviews",
            )

        update_data = review_data.model_dump(exclude_unset=True)
        if "rating" in update_data:
            update_data["anime_rating"] = update_data.pop("rating")
        for field, value in update_data.items():
            setattr(review, field, value)

        await db.commit()
        await db.refresh(review)
        return review


review_db = CRUDReview()
