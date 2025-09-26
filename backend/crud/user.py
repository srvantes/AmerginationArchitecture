from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional


from .base import CRUDBase
from ..database.models.user import User
from ..database.sсhemas.user import UserCreate, UserUpdate

class CRUDUser(CRUDBase[User, UserCreate, UserUpdate]):
    async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_username(self, db: AsyncSession, username: str) -> Optional[User]:
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_username_or_id(self, db: AsyncSession, identifier: str) -> Optional[User]:
        try:
            user_id = int(identifier)
            return await db.get(db, user_id)
        except ValueError:
            return await self.get_by_username(db, identifier)

    async def authenticate(self, db: AsyncSession, email: str, password: str) -> Optional[User]:

        from ..core.security import verify_password
        user = await self.get_by_email(db, email)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    async def is_active_us(self, user: User) -> bool:
        return user.is_active

    async def is_superuser(self, user: User) -> bool:
        return user.role == "admin"


'''    async def increment_profoile_views(self, db: AsyncSession, user_id: int) -> None:
        user = await self.get(db, user_id)
        if user:
            user.pro
'''
crud_user = CRUDUser()

