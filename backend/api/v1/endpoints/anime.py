from fastapi import Depends, APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional


from backend.database.models.anime import *
from backend.core.database import get_db
from backend.database.sсhemas.anime import BaseGenre
from backend.crud.anime import crud_anime



router = APIRouter(tags=["anime"])


@router.get("/anime/{anime_id}", response_model=Anime)
async def get_anime(
        anime_id: int, db: AsyncSession = Depends(get_db)
):
    anime = await crud_anime.get_by_id(db, anime_id)
    return anime

@router.get("/anime/search", response_model=Anime)
async def search_anime(
        query: str, db: AsyncSession = Depends(get_db)
):
    anime = await crud_anime.get_by_name(db, query)
    return anime



@router.get("/anime/filter/{genre}", response_model=Anime)
async def anime_list_by_genre(
        query: BaseGenre, db: AsyncSession = Depends(get_db)
):
    pass



@router.get("/anime", response_model=Anime)
async def get_anime_filtred(
        db: AsyncSession = Depends(get_db),
        genre: Optional[BaseGenre] = None,
        year: Optional[int] = None,
        status: Optional[str] = None,
        type: Optional[str] = None,
        voice_acting: Optional[str] = None,
):
    animes = await crud_anime.get_anime_by_filter(db, genre=genre, year=year, status=status, type=type, voice_acting=voice_acting)
    return animes

