from uuid import UUID
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Any, Dict
import datetime


from .base import CRUDBase
from ..database.models.anime import Anime
from ..database.sсhemas.anime import BaseAnimeDB, AnimeResponse


class CRUDAnime(CRUDBase[Anime, BaseAnimeDB, AnimeResponse]):
    def __init__(self):
        super().__init__(Anime)

    async def get_anime_by_id(self, db: AsyncSession, id: UUID) -> Optional[BaseAnimeDB]:
        result = await db.execute(select(BaseAnimeDB).where(BaseAnimeDB.id == id))
        return result.scalar_one_or_none()


    async def get_anime_by_name(self, db: AsyncSession, name: str) -> Optional[BaseAnimeDB]:
        result = await db.execute(select(BaseAnimeDB).where(AnimeResponse.title == name))
        return result.scalar_one_or_none()

    async def get_anime_by_filter(
            self,
            db: AsyncSession,
            genre: Optional = None,
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
        result = await self.get_by_filter(db, Anime, **filters)

        return result

crud_anime = CRUDAnime()