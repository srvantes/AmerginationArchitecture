from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, Security, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....core.config import settings
from ....core.database import get_db
from ....core.security import (
    create_access_token,
    get_current_user,
    oauth2_scheme,
    revoke_access_token,
)
from ....crud.user import crud_user
from ....database.models.user import User
from ....database.sсhemas.user import Token, UserCreate, UserLogin, UserMe, UserOut


router = APIRouter(tags=["authentication"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> User:
    if await crud_user.get_by_email(db, user_data.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    if await crud_user.get_by_username(db, user_data.username):
        raise HTTPException(status_code=409, detail="Username already taken")

    try:
        user = await crud_user.create_user_with_profile(user_data, db)
        await db.commit()
        await db.refresh(user)
        return user
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email or username already registered")


@router.post("/login", response_model=Token)
async def login(
    form_data: UserLogin,
    db: AsyncSession = Depends(get_db),
) -> Token:
    user = await crud_user.authenticate(db, form_data.username, form_data.password)
    if user is None or user.profile is None or not user.profile.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        user.id,
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserMe)
async def read_users_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    token: str = Security(oauth2_scheme),
    current_user: User = Depends(get_current_user),
) -> Response:
    await revoke_access_token(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
