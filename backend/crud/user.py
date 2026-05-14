from http.client import HTTPException
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import datetime


from .base import CRUDBase
from ..database.models.user import User, UserProfile
from ..database.sсhemas.user import UserCreate, UserUpdate, UserProfileUpdate
from ..core.password import get_password_hash

class CRUDUser(CRUDBase[User, UserCreate, UserUpdate]):
    def __init__(self):
        super().__init__(User)
    async def get_by_id(self, db, id: UUID) -> Optional[User]:
        result = await db.execute(
            select(User).where(User.id == id)
        )
        return await result

    async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_username(self, db: AsyncSession, username: str) -> Optional[User]:
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_user_by_email_or_username(self, db: AsyncSession, login: str) -> Optional[User]:
        from sqlalchemy import or_
        result = await db.execute(
            select(User).where(or_(User.email == login, User.username == login))
        )
        return result.scalar_one_or_none()

    async def get_by_username_or_id(self, db: AsyncSession, identifier: str) -> Optional[User]:
        try:
            user_id = int(identifier)
            return await self.get(db, user_id)
        except ValueError:
            return await self.get_by_username(db, identifier)

    async def authenticate(self, db: AsyncSession, identifer: str, password: str) -> Optional[User]:

        from ..core.password import verify_password
        user = await self.get_user_by_email_or_username(db, identifer)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    async def is_active_user(self, user: User) -> bool:
        return user.is_active

    async def is_superuser(self, user: User) -> bool:
        return user.role == "admin"

    async def create_user(self, user: UserCreate, db: AsyncSession) -> User:
        db_obj = User(
            hashed_password=get_password_hash(user.password),
            email=user.email,
            username=user.username,
            created_at=datetime.datetime.utcnow(),
        )

        db.add(db_obj)
        await db.commit()
        return db_obj

    async def get_user_profile(self, user_id: UUID, db: AsyncSession) -> Optional[UserProfile]:

        user_profile = await db.execute(
            select(UserProfile).where(User.id == user_id)
        )

        return user_profile.scalar_one_or_none()

    async def create_base_profile(self, user_id: UUID, db: AsyncSession) -> Optional[UserProfile]:
        existing = await db.execute(
            select(UserProfile).where(User.id == user_id)
        )
        if existing.scalar_one_or_none():
            return None

        profile = UserProfile(user_id=user_id)
        db.add(profile)

        await db.flush()
        await db.refresh(profile)

        return profile


    async def update_profile(self, db: AsyncSession, user_id: UUID, profile_data: UserProfileUpdate) -> UserProfile:
        result = await db.execute(
            select(UserProfile).where(User.id == user_id)
        )
        profile = result.scalar_one_or_none()

        if not profile:
            raise ValueError("Profile not found")

        update_dict = profile_data.model_dump(exclude=True)

        if "custom_url" in update_dict and update_dict["custom_url"] is not None:
            existing = await db.execute(
                select(UserProfile).where(
                    UserProfile.custom_url == update_dict["custom_url"],
                    UserProfile.user_id != user_id,
                )
            )
            if existing.scalar_one_or_none():
                raise ValueError("Custom_url already taken")

        for field, value in update_dict.items():
            setattr(profile, field, value)

        await db.commit()
        await db.refresh(profile)
        return profile


crud_user = CRUDUser()

