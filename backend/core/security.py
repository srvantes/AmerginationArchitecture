import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException, status
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
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


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


def create_access_token(user_id: UUID, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": str(user_id),
        "jti": str(uuid4()),
        "type": "access",
        "iat": now,
        "exp": expires_at,
    }
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


async def revoke_access_token(token: str) -> None:
    payload = decode_access_token(token)
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
    token: Annotated[str, Depends(oauth2_scheme)],
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_access_token(token)
    if await _is_token_revoked(payload["jti"]):
        raise credentials_exception()

    user = await crud_user.get_by_id(db, UUID(payload["sub"]))
    if user is None or user.profile is None or not user.profile.is_active:
        raise credentials_exception()
    return user


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
