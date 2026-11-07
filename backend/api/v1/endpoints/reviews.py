from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_optional_user
from backend.core.rate_limit import limited_review_create, limited_like, RATE_LIMIT_RESPONSES
from backend.crud.review import review_db
from backend.database.models.user import User
from backend.database.models.anime import Review
from backend.database.sсhemas.discussion import AnimeSource, AnimeId
from fastapi import Query
from backend.database.sсhemas.anime import ReviewCreate, ReviewOut, ReviewUpdate
from backend.services.discussion import change_review_reaction, review_rows


router = APIRouter(tags=["reviews"])


@router.get("/")
async def list_reviews(anime_source: AnimeSource, anime_external_id: AnimeId,
                       limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0),
                       user=Depends(get_optional_user), db: AsyncSession = Depends(get_db)):
    condition = (Review.anime_source == anime_source) & (Review.anime_external_id == anime_external_id)
    total = await db.execute(select(func.count()).select_from(Review).where(condition))
    items = await review_rows(db, condition, viewer=user.id if user else None, limit=limit, offset=offset)
    return {"total": total.scalar_one(), "items": items}


@router.post("/", response_model=ReviewOut, status_code=status.HTTP_201_CREATED, responses=RATE_LIMIT_RESPONSES)
async def write_review(
    review_data: ReviewCreate,
    current_user: User = Depends(limited_review_create),
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
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await review_rows(db, Review.id == review_id, viewer=user.id if user else None)
    if not rows:
        raise HTTPException(status_code=404, detail="Review not found")
    return rows[0]


@router.patch("/{review_id}", response_model=ReviewOut, responses=RATE_LIMIT_RESPONSES)
async def update_review(
    review_id: UUID,
    review_data: ReviewUpdate,
    current_user: User = Depends(limited_review_create),
    db: AsyncSession = Depends(get_db),
):
    review = await review_db.update_review(db, review_id, current_user.id, review_data)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return await get_review(review_id, current_user, db)


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT, responses=RATE_LIMIT_RESPONSES)
async def delete_review(
    review_id: UUID,
    current_user: User = Depends(limited_review_create),
    db: AsyncSession = Depends(get_db),
) -> Response:
    deleted = await review_db.delete_review(db, review_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Review not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{review_id}/{reaction}", response_model=ReviewOut, responses=RATE_LIMIT_RESPONSES)
@router.delete("/{review_id}/{reaction}", response_model=ReviewOut, responses=RATE_LIMIT_RESPONSES)
async def react_to_review(review_id: UUID, reaction: Literal["like", "dislike"], request: Request,
                          user: User = Depends(limited_like), db: AsyncSession = Depends(get_db)):
    value = 1 if reaction == "like" else -1
    return await change_review_reaction(db, review_id, user.id, value, request.method == "PUT")
