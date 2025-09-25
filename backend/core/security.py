from enum import Enum
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models.user import User


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    MODERATOR = "moderator"

class Permissions:
    # Права пользователей
    USER_BASIC = 'user:basic'
    #USER_PREMIUM = 'user:premium'


    # Права модератора
    MODERATE_REVIEWS = 'moderate:reviews'
    MODERATE_USERS = 'moderate:users'
    MANAGE_ANIME = 'manage:anime'

    # Права администратора
    MANAGE_USERS = 'manage:users'
    MANAGE_SYSTEM = 'manage:system'
    VIEW_STATS = 'view:stats'




ROLE_PERMISSIONS = {
    UserRole.USER: [Permissions.USER_BASIC],
    UserRole.MODERATOR: [
        Permissions.USER_BASIC,
        Permissions.MODERATE_REVIEWS,
        Permissions.MODERATE_USERS,
        Permissions.MANAGE_ANIME
    ],
    UserRole.ADMIN: [
        Permissions.USER_BASIC,
        Permissions.MODERATE_REVIEWS,
        Permissions.MODERATE_USERS,
        Permissions.MANAGE_ANIME,
        Permissions.MANAGE_USERS,
        Permissions.MANAGE_SYSTEM,
        Permissions.VIEW_STATS
    ],
}

async def get_current_user(db: AsyncSession) -> User:
    pass

async def check_permissions(user, permissions: str):
    if user.role not in ROLE_PERMISSIONS:
        raise HTTPException(
            status_code=403, detail="Access denied"
        )

    if permissions not in ROLE_PERMISSIONS[user.role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission {permissions} required"
        )

