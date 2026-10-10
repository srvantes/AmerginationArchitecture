from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.crud.review import review_db
from backend.database.models.user import User
from backend.database.models.anime import Review
from backend.database.sсhemas.discussion import AnimeSource, AnimeId
from fastapi import Query
from backend.database.sсhemas.anime import ReviewCreate, ReviewOut, ReviewUpdate


router = APIRouter(tags=["reviews"])


@router.get("/")
async def list_reviews(anime_source: AnimeSource, anime_external_id: AnimeId,
                       limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0),
                       db: AsyncSession = Depends(get_db)):
    condition = (Review.anime_source == anime_source) & (Review.anime_external_id == anime_external_id)
    total = await db.execute(select(func.count()).select_from(Review).where(condition))
    rows = await db.execute(select(Review).where(condition).order_by(Review.date.desc(), Review.id.desc()).limit(limit).offset(offset))
    return {"total": total.scalar_one(), "items": [ReviewOut.model_validate(item) for item in rows.scalars().all()]}


@router.post("/", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
async def write_review(
    review_data: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await review_db.write_review(db, current_user.id, review_data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Review for this anime already exists")


@router.get("/{review_id}", response_model=ReviewOut)
async def get_review(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    review = await review_db.get_review_by_id(db, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@router.patch("/{review_id}", response_model=ReviewOut)
async def update_review(
    review_id: UUID,
    review_data: ReviewUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = await review_db.update_review(db, review_id, current_user.id, review_data)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    deleted = await review_db.delete_review(db, review_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Review not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
