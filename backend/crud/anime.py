from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Any, Dict
import datetime


from .base import CRUDBase
from ..database.models.anime import Anime
from ..database.sсhemas.anime import BaseAnime, BaseReviews, BaseGenre


class CRUDAnime(CRUDBase[BaseAnime, BaseReviews, BaseGenre]):
    def __init__(self):
        super().__init__(Anime)

    async def get_anime_by_id(self, db: AsyncSession, id: int) -> Optional[Anime]:
        result = await db.execute(select(Anime).where(Anime.id == id))
        return result.scalar_one_or_none()


    async def get_anime_by_name(self, db: AsyncSession, name: str) -> Optional[Anime]:
        result = await db.execute(select(Anime).where(Anime.title == name))
        return result.scalar_one_or_none()

    async def get_anime_by_filter(
            self,
            db: AsyncSession,
            genre: Optional[BaseGenre] = None,
            year: Optional[int] = None,
            status: Optional[str] = None,
            type: Optional[str] = None,
            voice_acting: Optional[str] = None,
    ) -> List[Anime]:
        filters = {
        "genre": genre,
        "year": year,
        "status": status,
        "type": type,
        "voice_acting": voice_acting,
        }
        result = await CRUDBase.get_by_filter(db, Anime, **filters)

        return result

crud_anime = CRUDAnime()