from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.database.models.comment import Comment
from backend.database.models.user import User
from backend.database.sсhemas.discussion import CommentCreate, CommentUpdate, AnimeSource, AnimeId
from backend.services.discussion import comment_by_id, comment_rows, change_like, eligibility, lock_author

router = APIRouter(tags=["comments"])
optional_token = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def optional_user(token=Depends(optional_token), db=Depends(get_db)):
    return await get_current_user(token, db) if token else None


@router.get("/eligibility")
async def review_eligibility(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await eligibility(db, user)


@router.get("/")
async def list_comments(anime_source: AnimeSource, anime_external_id: AnimeId,
                        limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
                        user=Depends(optional_user), db: AsyncSession = Depends(get_db)):
    count = await db.execute(select(func.count()).select_from(Comment).where(
        Comment.anime_source == anime_source, Comment.anime_external_id == anime_external_id))
    return {"total": count.scalar_one(), "items": await comment_rows(
        db, anime_source, anime_external_id, viewer=user.id if user else None, limit=limit, offset=offset)}


@router.post("/", status_code=201)
async def create_comment(data: CommentCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    item = Comment(user_id=user.id, **data.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return (await comment_rows(db, comment_id=item.id, viewer=user.id))[0]


@router.patch("/{comment_id}")
async def edit_comment(comment_id: UUID, data: CommentUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    item = await comment_by_id(db, comment_id)
    if item.user_id != user.id:
        raise HTTPException(403, "Можно редактировать только свои комментарии")
    item.text, item.has_spoilers = data.text, data.has_spoilers
    await db.commit()
    return (await comment_rows(db, comment_id=comment_id, viewer=user.id))[0]


@router.delete("/{comment_id}", status_code=204)
async def remove_comment(comment_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    item = await comment_by_id(db, comment_id)
    if item.user_id != user.id:
        raise HTTPException(403, "Можно удалять только свои комментарии")
    await lock_author(db, item.user_id)
    item = await comment_by_id(db, comment_id)
    await db.delete(item)
    await db.commit()
    return Response(status_code=204)


@router.put("/{comment_id}/like")
async def like_comment(comment_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await change_like(db, comment_id, user.id, True)


@router.delete("/{comment_id}/like")
async def unlike_comment(comment_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await change_like(db, comment_id, user.id, False)
