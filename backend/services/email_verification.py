import hashlib
import hmac
import math
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select

from backend.core.config import settings
from backend.database.models.user import User
from backend.database.models.email_verification import EmailVerification
from backend.services.mailer import send_verification_email
from backend.services.achievements import sync_achievements

CODE_SECONDS = 120
MAX_ATTEMPTS = 5


def utc_now():
    return datetime.now(timezone.utc)


def aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def digest(user_id, code):
    return hmac.new(settings.SECRET_KEY.encode(), f"email:{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


async def locked_state(db, user_id):
    # Serialize challenges without blocking FK checks made while awarding achievements.
    result = await db.execute(select(User).where(User.id == user_id).with_for_update(key_share=True)
                              .execution_options(populate_existing=True))
    user = result.scalar_one()
    if user.email_verified:
        raise HTTPException(409, "Почта уже подтверждена")
    result = await db.execute(select(EmailVerification).where(EmailVerification.user_id == user_id))
    return user, result.scalar_one_or_none()


async def issue_code(db, user_id):
    user, state = await locked_state(db, user_id)
    now = utc_now()
    if state and aware(state.expires_at) > now:
        remaining = max(1, math.ceil((aware(state.expires_at) - now).total_seconds()))
        raise HTTPException(429, f"Повторный код можно отправить через {remaining} сек.",
                            headers={"Retry-After": str(remaining)})
    while True:
        code = f"{secrets.randbelow(1000000):06d}"
        hashed = digest(user.id, code)
        if state is None or not hmac.compare_digest(hashed, state.code_digest):
            break
    # SMTP failure rolls back the challenge; don't pretend a code was sent.
    await send_verification_email(user.email, code)
    if state is None:
        state = EmailVerification(user_id=user.id)
        db.add(state)
    state.code_digest, state.expires_at, state.attempts = hashed, utc_now() + timedelta(seconds=CODE_SECONDS), 0
    await db.flush()


async def confirm_code(db, user_id, code):
    user, state = await locked_state(db, user_id)
    now = utc_now()
    if state is None or aware(state.expires_at) <= now:
        raise HTTPException(400, "Код истёк или не был отправлен. Запросите новый код.")
    if state.attempts >= MAX_ATTEMPTS:
        raise HTTPException(429, "Попытки ввода закончились. Дождитесь возможности отправить новый код.",
                            headers={"Retry-After": str(max(1, math.ceil((aware(state.expires_at) - now).total_seconds())))})
    if not hmac.compare_digest(digest(user.id, code), state.code_digest):
        state.attempts += 1
        await db.commit()
        if state.attempts == MAX_ATTEMPTS:
            raise HTTPException(429, "Попытки ввода закончились. Запросите новый код после его истечения.",
                                headers={"Retry-After": str(max(1, math.ceil((aware(state.expires_at) - now).total_seconds())))})
        raise HTTPException(400, f"Неверный код. Осталось попыток: {MAX_ATTEMPTS - state.attempts}.")
    user.email_verified_at = now
    await db.delete(state)
    await sync_achievements(db, user.id)
    await db.commit()
    return {"email_verified": True}


async def code_status(db, user):
    result = await db.execute(select(EmailVerification).where(EmailVerification.user_id == user.id))
    state = result.scalar_one_or_none()
    remaining = max(0, math.ceil((aware(state.expires_at) - utc_now()).total_seconds())) if state else 0
    return {"email_verified": user.email_verified, "expires_in_seconds": remaining,
            "resend_after_seconds": remaining, "attempts_remaining": max(0, MAX_ATTEMPTS - state.attempts) if state else MAX_ATTEMPTS}
