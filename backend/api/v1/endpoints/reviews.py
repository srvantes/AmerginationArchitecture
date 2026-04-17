from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.database.sсhemas.anime import BaseReviews, CreateReview, BaseAnime

router = APIRouter(tags=["reviews"])


@router.post("/anime/{anime_id}", response_model=CreateReview)
async def write_review(
        anime_id: BaseAnime.id,
        review: BaseReviews,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
) -> CreateReview | None:
    return None
