import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from enum import Enum
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm, SecurityScopes, HTTPBearer
from jose import JWTError
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession



from .database import get_db
from backend.database.models.user import User
from .config import get_settings
from ..crud import crud_user

Settings = get_settings()
SECRET_KEY = Settings.SECRET_KEY
ALGORITHM = Settings.ALGORITHM


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

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
security = HTTPBearer


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)



def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=ALGORITHM)
        username: str = payload.get("sub")
        user_id: int = payload.get("user_id")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await crud_user.get_by_username_or_id(db, username)
    if user is None:
        raise credentials_exception
    return user


async def check_permissions(user, permissions: str):
    if user.role not in ROLE_PERMISSIONS:
        raise HTTPException(
            status_code=403, detail="Access denied"
        )

    if permissions not in ROLE_PERMISSIONS[user.role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission {permissions} required"
        )

async def authenticate_user(user_, db: AsyncSession = Depends(get_db)):
    user = await crud_user.get_by_email(db, email=user_.email)
    if not user:
        return False
    if not verify_password(user.password, user.hashed_password):
        return False
    return user