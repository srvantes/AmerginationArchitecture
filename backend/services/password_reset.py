import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, delete

from backend.core.config import settings
from backend.core.password import get_password_hash
from backend.database.models.user import User
from backend.database.models.password_reset import PasswordReset
from backend.database.models.email_verification import EmailVerification
from backend.services.email_verification import utc_now, aware, CODE_SECONDS, MAX_ATTEMPTS
from backend.services.mailer import send_password_reset_email

log = logging.getLogger(__name__)
GRANT_SECONDS = 300
INVALID_CODE = "Код неверен, истёк или попытки закончились. Запросите новый код."
REQUEST_MESSAGE = "Если для этой почты есть активный аккаунт с подтверждённым адресом, мы отправим код восстановления."


def digest(purpose, value):
    return hmac.new(settings.SECRET_KEY.encode(), f"reset:{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


async def locked_user(db, user_id):
    result = await db.execute(select(User).where(User.id == user_id).with_for_update()
                              .execution_options(populate_existing=True))
    return result.scalar_one_or_none()


def eligible(user):
    return bool(user and user.email_verified and user.profile and user.profile.is_active)


async def state_for(db, user_id):
    result = await db.execute(select(PasswordReset).where(PasswordReset.user_id == user_id)
                              .execution_options(populate_existing=True))
    return result.scalar_one_or_none()


async def deliver(email, code):
    try:
        await send_password_reset_email(email, code)
    except HTTPException:
        # Mail is sent after the identical HTTP response, so SMTP can't enumerate users.
        log.warning("Password recovery email delivery failed")


async def request_reset(db, user, background):
    if not eligible(user):
        return
    user = await locked_user(db, user.id)
    if not eligible(user):
        return
    state = await state_for(db, user.id)
    now = utc_now()
    if state and aware(state.expires_at) > now:
        return
    while True:
        code = f"{secrets.randbelow(1000000):06d}"
        hashed = digest(str(user.id), code)
        if state is None or not hmac.compare_digest(hashed, state.code_digest):
            break
    if state is None:
        state = PasswordReset(user_id=user.id)
        db.add(state)
    state.code_digest = hashed
    state.expires_at = now + timedelta(seconds=CODE_SECONDS)
    state.attempts = 0
    state.grant_digest = state.grant_expires_at = None
    await db.commit()
    background.add_task(deliver, user.email, code)


async def verify_code(db, user, code):
    if not eligible(user):
        raise HTTPException(400, INVALID_CODE)
    user = await locked_user(db, user.id)
    if not eligible(user):
        raise HTTPException(400, INVALID_CODE)
    state = await state_for(db, user.id)
    now = utc_now()
    if state is None or aware(state.expires_at) <= now or state.attempts >= MAX_ATTEMPTS or state.grant_digest:
        raise HTTPException(400, INVALID_CODE)
    if not hmac.compare_digest(digest(str(user.id), code), state.code_digest):
        state.attempts += 1
        await db.commit()
        raise HTTPException(400, INVALID_CODE)
    token = secrets.token_urlsafe(32)
    state.grant_digest = digest("grant", token)
    state.grant_expires_at = now + timedelta(seconds=GRANT_SECONDS)
    await db.commit()
    return {"reset_token": token, "expires_in_seconds": GRANT_SECONDS}


async def finish_reset(db, token, password):
    token_digest = digest("grant", token)
    result = await db.execute(select(PasswordReset.user_id).where(PasswordReset.grant_digest == token_digest))
    user_id = result.scalar_one_or_none()
    if user_id is None:
        raise HTTPException(400, "Разрешение на смену пароля истекло или уже использовано. Начните восстановление заново.")
    user = await locked_user(db, user_id)
    state = await state_for(db, user_id)
    if not eligible(user) or state is None or not state.grant_digest or not hmac.compare_digest(state.grant_digest, token_digest) or aware(state.grant_expires_at) <= utc_now():
        raise HTTPException(400, "Разрешение на смену пароля истекло или уже использовано. Начните восстановление заново.")
    user.hashed_password = get_password_hash(password)
    user.auth_version += 1
    await db.delete(state)
    await db.execute(delete(EmailVerification).where(EmailVerification.user_id == user_id))
    await db.commit()
    return {"detail": "Пароль изменён. Войдите с новым паролем."}
