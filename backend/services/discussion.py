from sqlalchemy import func, literal, select
from sqlalchemy.orm import aliased
from fastapi import HTTPException
from backend.database.models.anime import Review, ReviewVote
from backend.database.models.comment import Comment, CommentLike
from backend.database.models.user import User
from backend.database.sсhemas.anime import ReviewOut
from backend.services.achievements import sync_achievements
from backend.services.points import COMMENT_LIKE_POINTS, REVIEW_LIKE_POINTS, award_points, lock_profile

REVIEW_LIKES_REQUIRED = 11


async def likes_received(db, user_id):
    result = await db.execute(select(func.count()).select_from(CommentLike).join(
        Comment, Comment.id == CommentLike.comment_id).where(Comment.user_id == user_id, CommentLike.value == 1))
    return result.scalar_one()


async def eligibility(db, user):
    return {"can_write_reviews": user.profile.can_write_reviews,
            "likes_received": await likes_received(db, user.id), "likes_required": REVIEW_LIKES_REQUIRED}


async def comment_by_id(db, comment_id, *, lock=False):
    query = select(Comment).where(Comment.id == comment_id)
    result = await db.execute(query.with_for_update() if lock else query)
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "Комментарий не найден")
    return item


def reaction_columns(model, target_column, target_id, viewer):
    target = target_column == target_id
    likes = select(func.count()).select_from(model).where(target, model.value == 1).scalar_subquery()
    dislikes = select(func.count()).select_from(model).where(target, model.value == -1).scalar_subquery()
    vote = select(model.value).where(target, model.user_id == viewer).scalar_subquery() if viewer else literal(None)
    return likes, dislikes, vote


def reaction_data(likes, dislikes, vote):
    return {"likes_count": likes, "dislikes_count": dislikes, "liked_by_me": vote == 1, "disliked_by_me": vote == -1}


async def comment_rows(db, source=None, external_id=None, viewer=None, comment_id=None, parent_id=None, limit=20, offset=0):
    child = aliased(Comment)
    reply_count = select(func.count()).select_from(child).where(child.parent_id == Comment.id).scalar_subquery()
    votes = reaction_columns(CommentLike, CommentLike.comment_id, Comment.id, viewer)
    query = select(Comment, User.username, reply_count, *votes).join(User, User.id == Comment.user_id)
    if comment_id is not None:
        condition = Comment.id == comment_id
    elif parent_id is not None:
        condition = Comment.parent_id == parent_id
    else:
        condition = (Comment.anime_source == source) & (Comment.anime_external_id == external_id) & Comment.parent_id.is_(None)
    result = await db.execute(query.where(condition).order_by(Comment.created_at.desc(), Comment.id.desc()).limit(limit).offset(offset))
    return [{"id": item.id, "user_id": item.user_id, "author_name": author,
             "anime_source": item.anime_source, "anime_external_id": item.anime_external_id,
             "parent_id": item.parent_id, "reply_count": replies, "text": item.text, "has_spoilers": item.has_spoilers,
             "created_at": item.created_at, "updated_at": item.updated_at,
             **reaction_data(likes, dislikes, vote)}
            for item, author, replies, likes, dislikes, vote in result.all()]


async def set_reaction(db, model, target, target_id, user_id, value, wanted):
    result = await db.execute(select(model).where(target == target_id, model.user_id == user_id))
    existing = result.scalar_one_or_none()
    changed_to_like = wanted and value == 1 and (existing is None or existing.value != value)
    if wanted:
        if existing is None:
            db.add(model(**{target.key: target_id}, user_id=user_id, value=value))
        else:
            existing.value = value
    elif existing is not None and existing.value == value:
        await db.delete(existing)
    await db.flush()
    return changed_to_like


async def change_comment_reaction(db, comment_id, user_id, value, wanted):
    comment = await comment_by_id(db, comment_id)
    if comment.user_id == user_id:
        raise HTTPException(403, "Нельзя оценивать свои комментарии")
    profile = await lock_profile(db, comment.user_id)
    # Deletion uses the same author lock; verify the comment still exists after waiting.
    comment = await comment_by_id(db, comment_id)
    liked = await set_reaction(db, CommentLike, CommentLike.comment_id, comment_id, user_id, value, wanted)
    if liked:
        await award_points(db, comment.user_id, f"comment-like:{comment_id}:{user_id}", COMMENT_LIKE_POINTS)
    if wanted and value == 1:
        if not profile.can_write_reviews and await likes_received(db, comment.user_id) >= REVIEW_LIKES_REQUIRED:
            profile.can_write_reviews = True
        await sync_achievements(db, comment.user_id)
    await db.commit()
    rows = await comment_rows(db, comment_id=comment_id, viewer=user_id)
    if not rows:
        raise HTTPException(404, "Комментарий не найден")
    return rows[0]


async def review_rows(db, condition, viewer=None, limit=20, offset=0):
    votes = reaction_columns(ReviewVote, ReviewVote.review_id, Review.id, viewer)
    result = await db.execute(select(Review, *votes).where(condition)
                              .order_by(Review.date.desc(), Review.id.desc()).limit(limit).offset(offset))
    return [{**ReviewOut.model_validate(item).model_dump(), **reaction_data(likes, dislikes, vote)}
            for item, likes, dislikes, vote in result.all()]


async def change_review_reaction(db, review_id, user_id, value, wanted):
    query = select(Review).where(Review.id == review_id)
    author = (await db.execute(select(Review.user_id).where(Review.id == review_id))).scalar_one_or_none()
    if author is None:
        raise HTTPException(404, "Рецензия не найдена")
    if author == user_id:
        raise HTTPException(403, "Нельзя оценивать свои рецензии")
    await lock_profile(db, author)
    review = (await db.execute(query.with_for_update(of=Review))).scalar_one_or_none()
    if review is None:
        raise HTTPException(404, "Рецензия не найдена")
    if await set_reaction(db, ReviewVote, ReviewVote.review_id, review_id, user_id, value, wanted):
        key = f"review-like:{review.anime_source}:{review.anime_external_id}:{user_id}"
        await award_points(db, author, key, REVIEW_LIKE_POINTS)
    await db.commit()
    rows = await review_rows(db, Review.id == review_id, viewer=user_id)
    if not rows:
        raise HTTPException(404, "Рецензия не найдена")
    return rows[0]
