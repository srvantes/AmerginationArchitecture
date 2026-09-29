from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .base import CRUDBase
from ..core.password import get_password_hash, verify_password
from ..database.models.user import User, UserProfile
from ..database.sсhemas.user import UserCreate, UserProfileUpdate, UserUpdate


class CRUDUser(CRUDBase[User, UserCreate, UserUpdate]):
    def __init__(self):
        super().__init__(User)

    @staticmethod
    def _with_profile():
        return select(User).options(selectinload(User.profile))

    async def get_by_id(self, db: AsyncSession, user_id: UUID) -> Optional[User]:
        result = await db.execute(self._with_profile().where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        result = await db.execute(self._with_profile().where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_username(self, db: AsyncSession, username: str) -> Optional[User]:
        result = await db.execute(self._with_profile().where(User.username == username))
        return result.scalar_one_or_none()

    async def get_user_by_email_or_username(self, db: AsyncSession, login: str) -> Optional[User]:
        result = await db.execute(
            self._with_profile().where(or_(User.email == login, User.username == login))
        )
        return result.scalar_one_or_none()

    async def get_by_username_or_id(self, db: AsyncSession, identifier: str) -> Optional[User]:
        try:
            return await self.get_by_id(db, UUID(identifier))
        except ValueError:
            return await self.get_by_username(db, identifier)

    async def authenticate(self, db: AsyncSession, identifier: str, password: str) -> Optional[User]:
        user = await self.get_user_by_email_or_username(db, identifier)
        if user is None or not verify_password(password, user.hashed_password):
            return None
        return user

    async def create_user_with_profile(self, user_data: UserCreate, db: AsyncSession) -> User:
        user = User(
            hashed_password=get_password_hash(user_data.password),
            email=user_data.email,
            username=user_data.username,
        )
        db.add(user)
        await db.flush()

        db.add(UserProfile(id=user.id))
        await db.flush()
        await db.refresh(user)
        return user

    async def get_user_profile(self, db: AsyncSession, user_id: UUID) -> Optional[UserProfile]:
        result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
        return result.scalar_one_or_none()

    async def update_profile(
        self,
        db: AsyncSession,
        user_id: UUID,
        profile_data: UserProfileUpdate,
    ) -> UserProfile:
        profile = await self.get_user_profile(db, user_id)
        if profile is None:
            raise ValueError("Profile not found")

        update_data = profile_data.model_dump(exclude_unset=True)
        custom_url = update_data.get("custom_url")
        if custom_url is not None:
            existing = await db.execute(
                select(UserProfile).where(
                    UserProfile.custom_url == custom_url,
                    UserProfile.id != user_id,
                )
            )
            if existing.scalar_one_or_none():
                raise ValueError("Custom URL already taken")

        for field, value in update_data.items():
            setattr(profile, field, value)

        await db.commit()
        await db.refresh(profile)
        return profile


crud_user = CRUDUser()
