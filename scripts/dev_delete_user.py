"""Local development only: preview or delete one user and optional IP quotas.

python -m scripts.dev_delete_user --email test@example.com
python -m scripts.dev_delete_user --email test@example.com --confirm --reset-ip 127.0.0.1
"""
import argparse
import asyncio

from sqlalchemy import delete, select, func, or_

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal, engine
from backend.core.redis import redis_client
from backend.core.rate_limit import identity
from backend.database.models.user import User, UserProfile, UserBadge
from backend.database.models.comment import Comment, CommentLike
from backend.database.models.anime import Review
from backend.database.models.watchlist import WatchlistEntry
from backend.database.models.email_verification import EmailVerification
from backend.database.models.password_reset import PasswordReset


async def run(email, confirm=False, reset_ips=()):
    if settings.POSTGRES_HOST not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Команда предназначена только для локальной базы разработки")
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User).where(func.lower(User.email) == email.strip().lower())
                                  .with_for_update())).scalars().all()
        if not users:
            print("Аккаунт с этой почтой не найден.")
            return False
        if len(users) != 1:
            raise RuntimeError("Найдено несколько аккаунтов; удаление отменено")
        user = users[0]
        user_id, username, account_email = user.id, user.username, user.email
        print(f"Аккаунт: {username} / {account_email} / {user_id}")
        owned_comments = select(Comment.id).where(Comment.user_id == user_id)
        related = [
            (UserProfile, UserProfile.id == user_id),
            (UserBadge, UserBadge.user_id == user_id),
            (Comment, Comment.user_id == user_id),
            (CommentLike, or_(CommentLike.user_id == user_id, CommentLike.comment_id.in_(owned_comments))),
            (Review, Review.user_id == user_id),
            (WatchlistEntry, WatchlistEntry.user_id == user_id),
            (EmailVerification, EmailVerification.user_id == user_id),
            (PasswordReset, PasswordReset.user_id == user_id),
        ]
        for model, condition in related:
            count = (await db.execute(select(func.count()).select_from(model).where(condition))).scalar_one()
            print(f"  {model.__tablename__}: {count}")
        if not confirm:
            print("Просмотр без удаления. Для удаления добавьте --confirm.")
            if reset_ips:
                print("Лимиты также не сброшены: нужен --confirm.")
            return False
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()
        remaining = (await db.execute(select(func.count()).select_from(User).where(User.id == user_id))).scalar_one()
        if remaining:
            raise RuntimeError("Не удалось подтвердить удаление аккаунта")
        print("Аккаунт и связанные записи удалены каскадно.")

    # Exact keys only: don't flush Redis or remove other users' cache/limits.
    keys = [f"rate:v1:{{limits}}:{action}:{identity(user_id)}" for action in (
        "comment-hour", "comment-cooldown", "discussion-edit", "like", "review-create", "email-send")]
    keys.extend(f"rate:v1:{{limits}}:{action}:{identity(account_email.strip().lower())}" for action in ("reset-email", "reset-pause"))
    for ip in reset_ips:
        keys.extend(f"rate:v1:{{limits}}:{action}:{identity(ip)}" for action in ("registration", "login-ip", "reset-ip", "reset-attempt"))
        for login in (username, account_email):
            keys.append(f"rate:v1:{{limits}}:login-account-ip:{identity(ip + ':' + login.strip().casefold())}")
    try:
        await redis_client.delete(*keys)
        print("Лимиты удалённого аккаунта и указанных IP сброшены.")
    except Exception as error:
        print(f"Аккаунт удалён, но лимиты Redis не сброшены ({type(error).__name__}).")
    return True


async def main():
    parser = argparse.ArgumentParser(description="Удаление одного аккаунта из локальной базы разработки")
    parser.add_argument("--email", required=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--reset-ip", action="append", default=[], help="Сбросить лимиты регистрации/входа этого IP")
    args = parser.parse_args()
    try:
        await run(args.email, args.confirm, args.reset_ip)
    finally:
        await redis_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
