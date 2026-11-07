from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.core.database import get_db
from backend.core.security import get_current_user, get_optional_user
from backend.core.rate_limit import limited_comment_create, limited_discussion_edit, limited_like, RATE_LIMIT_RESPONSES
from backend.database.models.comment import Comment
from backend.database.models.user import User
from backend.database.sсhemas.discussion import CommentCreate, CommentUpdate, AnimeSource, AnimeId
from backend.services.discussion import comment_by_id, comment_rows, change_comment_reaction, eligibility
from backend.services.points import COMMENT_POINTS, award_points, lock_profile

router = APIRouter(tags=["comments"])


@router.get("/eligibility")
async def review_eligibility(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await eligibility(db, user)


@router.get("/")
async def list_comments(anime_source: AnimeSource, anime_external_id: AnimeId,
                        limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
                        user=Depends(get_optional_user), db: AsyncSession = Depends(get_db)):
    count = await db.execute(select(func.count()).select_from(Comment).where(
        Comment.anime_source == anime_source, Comment.anime_external_id == anime_external_id, Comment.parent_id.is_(None)))
    return {"total": count.scalar_one(), "items": await comment_rows(
        db, anime_source, anime_external_id, viewer=user.id if user else None, limit=limit, offset=offset)}


@router.get("/{comment_id}/replies")
async def list_replies(comment_id: UUID, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
                       user=Depends(get_optional_user), db: AsyncSession = Depends(get_db)):
    await comment_by_id(db, comment_id)
    count = await db.execute(select(func.count()).select_from(Comment).where(Comment.parent_id == comment_id))
    items = await comment_rows(db, parent_id=comment_id, viewer=user.id if user else None, limit=limit, offset=offset)
    return {"total": count.scalar_one(), "items": items}


@router.post("/", status_code=201, responses=RATE_LIMIT_RESPONSES)
async def create_comment(data: CommentCreate, user: User = Depends(limited_comment_create), db: AsyncSession = Depends(get_db)):
    await lock_profile(db, user.id)
    if data.parent_id is not None:
        parent = await comment_by_id(db, data.parent_id, lock=True)
        if (parent.anime_source, parent.anime_external_id) != (data.anime_source, data.anime_external_id):
            raise HTTPException(422, "Ответ должен относиться к тому же аниме")
    item = Comment(user_id=user.id, **data.model_dump())
    db.add(item)
    await db.flush()
    await award_points(db, user.id, f"comment:{item.id}", COMMENT_POINTS)
    await db.commit()
    await db.refresh(item)
    return (await comment_rows(db, comment_id=item.id, viewer=user.id))[0]


@router.patch("/{comment_id}", responses=RATE_LIMIT_RESPONSES)
async def edit_comment(comment_id: UUID, data: CommentUpdate, user: User = Depends(limited_discussion_edit), db: AsyncSession = Depends(get_db)):
    item = await comment_by_id(db, comment_id)
    if item.user_id != user.id:
        raise HTTPException(403, "Можно редактировать только свои комментарии")
    item.text, item.has_spoilers = data.text, data.has_spoilers
    await db.commit()
    return (await comment_rows(db, comment_id=comment_id, viewer=user.id))[0]


@router.delete("/{comment_id}", status_code=204, responses=RATE_LIMIT_RESPONSES)
async def remove_comment(comment_id: UUID, user: User = Depends(limited_discussion_edit), db: AsyncSession = Depends(get_db)):
    item = await comment_by_id(db, comment_id)
    if item.user_id != user.id:
        raise HTTPException(403, "Можно удалять только свои комментарии")
    await lock_profile(db, item.user_id)
    item = await comment_by_id(db, comment_id)
    await db.delete(item)
    await db.commit()
    return Response(status_code=204)


@router.put("/{comment_id}/{reaction}", responses=RATE_LIMIT_RESPONSES)
@router.delete("/{comment_id}/{reaction}", responses=RATE_LIMIT_RESPONSES)
async def react_to_comment(comment_id: UUID, reaction: Literal["like", "dislike"], request: Request,
                           user: User = Depends(limited_like), db: AsyncSession = Depends(get_db)):
    value = 1 if reaction == "like" else -1
    return await change_comment_reaction(db, comment_id, user.id, value, request.method == "PUT")
