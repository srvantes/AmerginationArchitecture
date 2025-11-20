from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models.user import UserProfile as UserProfile_db
from backend.database.sсhemas.user import UserProfile as UserProfile_sh

router = APIRouter(tags=['profile'])

