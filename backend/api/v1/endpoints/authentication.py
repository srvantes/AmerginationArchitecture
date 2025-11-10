from fastapi import Depends, APIRouter, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import timedelta

from watchfiles import awatch

from ....core.config import settings
from ....core.database import get_db
from ....database.sсhemas.user import UserCreate, UserProfile, Token
from ....core.security import create_access_token, authenticate_user
from ....crud.user import crud_user

router = APIRouter(tags=["authentication"])

@router.post("/login", response_model=UserCreate)
async def register(
        user_data: UserCreate = Depends(UserCreate),
        db: AsyncSession = Depends(get_db),
):
    if await crud_user.get_by_email(db, email=user_data.email):
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )


    if await crud_user.get_by_username(db, username=user_data.username):
        raise HTTPException(
            status_code=400,
            detail="Username already taken"
        )

    return crud_user.create(user_data, db)
