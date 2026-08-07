from datetime import datetime
from http.client import HTTPException
from typing import Optional
from uuid import UUID


from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Review
from backend.database.models.user import User
from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.database.sсhemas.anime import BaseReviews, CreateReview, UpdateReview
from backend.crud.review import review_db
router = APIRouter(tags=["reviews"])


@router.post("/profile/{user_id}/{review_id}", status_code=200)
async def write_review(
        user_id: UUID,
        anime_id: UUID,
        review: BaseReviews,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
) -> CreateReview | None:
    new_review = review_db.write_review(
        text=review.text,
        user_id=current_user.id,
        anime_id=anime_id,
        anime_title=review.anime_title,
        anime_rating=review.anime_rating
    )
    if not new_review:
        return None
    return new_review

@router.get("/profile/{user_id}/{review_id}", response_model=BaseReviews)
async def get_review(
        review_id: UUID,
        db: AsyncSession = Depends(get_db),
) -> Optional[BaseReviews]:
    review = review_db.get_review_by_id(review_id, db)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review

@router.post("/profile/{user_id}/{review_id}", status_code=200)
async def delete_review(
        review_id: UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    result = review_db.delete_review(review_id, current_user.id)
    if not result:
        raise HTTPException(status_code=404, detail="Could not delete review")
    return result

@router.post("/profile/{user_id}/{review_id}", status_code=200)
async def update_review(
        review_id: UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        date: Optional[datetime] = None,
) -> Optional[BaseReviews]:
    result = review_db.update_review(review_id, current_user.id, db, date)
    if not result:
        raise HTTPException(status_code=404, detail="Could not update review")
    return result