from fastapi import Depends, APIRouter, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List


from backend.services.shikimori_client import search_anime_cashed, get_anime_details_cached


'''
from backend.core.database import get_db
from backend.database.sсhemas.anime import BaseAnimeDB, AnimeResponse
from backend.crud.anime import crud_anime

'''

router = APIRouter(tags=["anime"])

@router.get("/search")
async def search_anime(q:str = Query(..., min_length=2, description="Название произведения")):

    result = await search_anime_cashed(q)
    return result

@router.get("/details",)
async def get_anime(shikimori_link: str = Query(..., description="Линк на аниме")):
    result = await get_anime_details_cached(shikimori_link)
    return result