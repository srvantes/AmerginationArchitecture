from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import datetime


from .base import CRUDBase
from ..database.models.user import User
from ..database.sсhemas.user import UserCreate, UserUpdate
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

    async def get_by_username_or_email(self, db: AsyncSession, identifier: str) -> Optional[User]:
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


'''    async def increment_profoile_views(self, db: AsyncSession, user_id: int) -> None:
        user = await self.get(db, user_id)
        if user:
            user.pro
'''
crud_user = CRUDUser()

