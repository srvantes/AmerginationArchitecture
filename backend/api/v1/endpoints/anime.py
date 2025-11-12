from fastapi import Depends, APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models.anime import *
from backend.core.database import get_db


router = APIRouter(tags=["anime"])


@router.get("/anime/{anime_id}", response_model=Anime)
async def get_anime(
        anime_id: int, db: AsyncSession = Depends(get_db)
):
    anime = await get_anime(anime_id, db)
@router.get("/anime/search", response_model=Anime)
async def search_anime(
        query: str, db: AsyncSession = Depends(get_db)
):
    pass

