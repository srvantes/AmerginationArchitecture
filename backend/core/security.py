import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models.user import User

from .config import settings
from .database import get_db
from .redis import redis_client
from ..crud import crud_user


logger = logging.getLogger(__name__)
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
WEB_SESSION_COOKIE = "amergination_session"
WEB_SESSION_IDLE_SECONDS = 3600
WEB_SESSION_MAX_SECONDS = 30 * 24 * 3600


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    MODERATOR = "moderator"


class Permissions:
    USER_BASIC = "user:basic"
    MODERATE_REVIEWS = "moderate:reviews"
    MODERATE_USERS = "moderate:users"
    MANAGE_ANIME = "manage:anime"
    MANAGE_USERS = "manage:users"
    MANAGE_SYSTEM = "manage:system"
    VIEW_STATS = "view:stats"


ROLE_PERMISSIONS = {
    UserRole.USER: {Permissions.USER_BASIC},
    UserRole.MODERATOR: {
        Permissions.USER_BASIC,
        Permissions.MODERATE_REVIEWS,
        Permissions.MODERATE_USERS,
        Permissions.MANAGE_ANIME,
    },
    UserRole.ADMIN: {
        Permissions.USER_BASIC,
        Permissions.MODERATE_REVIEWS,
        Permissions.MODERATE_USERS,
        Permissions.MANAGE_ANIME,
        Permissions.MANAGE_USERS,
        Permissions.MANAGE_SYSTEM,
        Permissions.VIEW_STATS,
    },
}


def credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_access_token(user_id: UUID, expires_delta: timedelta | None = None, token_version: int = 0,
                        *, web_session: bool = False) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": str(user_id),
        "jti": str(uuid4()),
        "type": "access",
        "iat": now,
        "exp": expires_at,
        "v": token_version,
    }
    if web_session:
        payload["web_session"] = True
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require": ["sub", "jti", "exp", "type"]},
        )
        if payload["type"] != "access":
            raise credentials_exception()
        UUID(payload["sub"])
        UUID(payload["jti"])
        return payload
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        raise credentials_exception()


async def _is_token_revoked(jti: str) -> bool:
    try:
        return bool(await redis_client.exists(f"revoked-token:{jti}"))
    except RedisError as exc:
        logger.warning("Redis unavailable during token check: %s", exc)
        return False


def _session_key(jti):
    return f"web-session:{jti}"


def _session_unavailable():
    return HTTPException(503, "Сервис сессий временно недоступен")


async def issue_web_session(user_id: UUID, token_version: int) -> str:
    token = create_access_token(user_id, timedelta(seconds=WEB_SESSION_MAX_SECONDS),
                                token_version, web_session=True)
    payload = decode_access_token(token)
    try:
        await redis_client.setex(_session_key(payload["jti"]), WEB_SESSION_IDLE_SECONDS, "1")
    except RedisError:
        raise _session_unavailable() from None
    return token


async def touch_web_session(token: str):
    payload = decode_access_token(token)
    if payload.get("web_session") is not True:
        raise credentials_exception()
    try:
        if not await redis_client.expire(_session_key(payload["jti"]), WEB_SESSION_IDLE_SECONDS):
            raise credentials_exception()
    except RedisError:
        raise _session_unavailable() from None


def request_token(request: Request, bearer: str | None = Depends(optional_oauth2_scheme)) -> str | None:
    if bearer:
        return bearer
    if request.headers.get("X-Amergination-Client") != "web":
        return None
    token = request.cookies.get(WEB_SESSION_COOKIE)
    if token:
        payload = decode_access_token(token)
        expected = request.headers.get("X-Amergination-Account")
        if payload.get("web_session") is not True or (expected and expected != payload["sub"]):
            raise credentials_exception()
    return token


async def revoke_access_token(token: str) -> None:
    payload = decode_access_token(token)
    if payload.get("web_session") is True:
        try:
            await redis_client.delete(_session_key(payload["jti"]))
        except RedisError:
            raise _session_unavailable() from None
        return
    ttl = int(payload["exp"] - datetime.now(timezone.utc).timestamp())
    if ttl <= 0:
        return
    try:
        await redis_client.setex(f"revoked-token:{payload['jti']}", ttl, "1")
    except RedisError as exc:
        logger.warning("Redis unavailable during logout: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token revocation service is unavailable",
        )


async def get_current_user(
    token: Annotated[str | None, Depends(request_token)],
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise credentials_exception()
    payload = decode_access_token(token)
    if payload.get("web_session") is True:
        try:
            exists = await redis_client.exists(_session_key(payload["jti"]))
        except RedisError:
            raise _session_unavailable() from None
        if not exists:
            raise credentials_exception()
    elif await _is_token_revoked(payload["jti"]):
        raise credentials_exception()

    user = await crud_user.get_by_id(db, UUID(payload["sub"]))
    if user is None or user.profile is None or not user.profile.is_active:
        raise credentials_exception()
    version = payload.get("v", 0)
    if type(version) is not int or version != user.auth_version:
        raise credentials_exception()
    return user


async def get_verified_user(user: User = Depends(get_current_user)) -> User:
    if not user.email_verified:
        raise HTTPException(403, "Подтвердите почту, чтобы публиковать тексты и ставить лайки")
    return user


async def get_optional_user(token: str | None = Depends(request_token),
                            db: AsyncSession = Depends(get_db)) -> User | None:
    if token is None:
        return None
    return await get_current_user(token, db)


def require_permission(permission: str):
    async def permission_dependency(user: User = Depends(get_current_user)) -> User:
        try:
            role = UserRole(user.profile.role)
        except (AttributeError, ValueError):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        if permission not in ROLE_PERMISSIONS[role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission {permission} required",
            )
        return user

    return permission_dependency
