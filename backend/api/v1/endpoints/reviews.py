from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models.anime import Anime
from backend.database.sсhemas.anime import BaseReviews, CreateReview

router = APIRouter(tags=["reviews"])


@router.post("/anime/{anime_id}", response_model=CreateReview)
async def write_review(
        review_data: CreateReview,
        db: AsyncSession,
):
    pass
