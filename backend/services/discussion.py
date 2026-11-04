from sqlalchemy import select, func, delete, literal
from fastapi import HTTPException
from backend.database.models.comment import Comment, CommentLike
from backend.database.models.user import User, UserProfile
from backend.services.achievements import sync_achievements

REVIEW_LIKES_REQUIRED = 11


async def likes_received(db, user_id):
    result = await db.execute(select(func.count()).select_from(CommentLike).join(
        Comment, Comment.id == CommentLike.comment_id).where(Comment.user_id == user_id))
    return result.scalar_one()


async def eligibility(db, user):
    return {"can_write_reviews": user.profile.can_write_reviews,
            "likes_received": await likes_received(db, user.id), "likes_required": REVIEW_LIKES_REQUIRED}


async def comment_by_id(db, comment_id):
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "Комментарий не найден")
    return item


async def lock_author(db, author_id):
    result = await db.execute(select(UserProfile).where(UserProfile.id == author_id).with_for_update()
                              .execution_options(populate_existing=True))
    return result.scalar_one()


async def comment_rows(db, source=None, external_id=None, viewer=None, comment_id=None, limit=20, offset=0):
    counts = select(CommentLike.comment_id, func.count().label("total")).group_by(CommentLike.comment_id).subquery()
    liked = select(CommentLike.comment_id).where(
        CommentLike.comment_id == Comment.id, CommentLike.user_id == viewer).exists() if viewer else literal(False)
    query = select(Comment, User.username, func.coalesce(counts.c.total, 0), liked).join(
        User, User.id == Comment.user_id).outerjoin(counts, counts.c.comment_id == Comment.id)
    condition = Comment.id == comment_id if comment_id else (
        (Comment.anime_source == source) & (Comment.anime_external_id == external_id))
    result = await db.execute(query.where(condition).order_by(Comment.created_at.desc(), Comment.id.desc()).limit(limit).offset(offset))
    return [{"id": item.id, "user_id": item.user_id, "author_name": author,
             "anime_source": item.anime_source, "anime_external_id": item.anime_external_id,
             "text": item.text, "has_spoilers": item.has_spoilers,
             "created_at": item.created_at, "updated_at": item.updated_at,
             "likes_count": count, "liked_by_me": bool(is_liked)}
            for item, author, count, is_liked in result.all()]


async def change_like(db, comment_id, user_id, wanted):
    comment = await comment_by_id(db, comment_id)
    if comment.user_id == user_id:
        raise HTTPException(403, "Нельзя ставить лайки своим комментариям")
    profile = await lock_author(db, comment.user_id)
    # Deletion uses the same author lock; verify the comment still exists after waiting.
    comment = await comment_by_id(db, comment_id)
    result = await db.execute(select(CommentLike).where(
        CommentLike.comment_id == comment_id, CommentLike.user_id == user_id))
    existing = result.scalar_one_or_none()
    if wanted and existing is None:
        db.add(CommentLike(comment_id=comment_id, user_id=user_id))
        await db.flush()
    elif not wanted and existing is not None:
        await db.delete(existing)
        await db.flush()
    if wanted and not profile.can_write_reviews and await likes_received(db, comment.user_id) >= REVIEW_LIKES_REQUIRED:
        profile.can_write_reviews = True
    if wanted:
        await sync_achievements(db, comment.user_id)
    await db.commit()
    rows = await comment_rows(db, comment_id=comment_id, viewer=user_id)
    if not rows:
        raise HTTPException(404, "Комментарий не найден")
    return rows[0]
