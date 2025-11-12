from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import datetime


from .base import CRUDBase
from ..database.models.anime import Anime
from ..database.sсhemas.anime import BaseAnime, BaseReviews, BaseGenre


class CRUDAnime(CRUDBase[BaseAnime, BaseReviews, BaseGenre]):
    def __init__(self):
        super().__init__(Anime)

    async def get_by_id(self, db: AsyncSession, id: int) -> Optional[Anime]:
        pass

    async def get_by_name(self, db: AsyncSession, name: str) -> Optional[Anime]:
        pass

    async def get_by_filter(self, db: AsyncSession, **kwargs) -> Optional[Anime]:
        pass

