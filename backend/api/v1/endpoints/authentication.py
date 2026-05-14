from fastapi import Depends, APIRouter, HTTPException, status, Header, Security
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import timedelta
from redis.asyncio import Redis

#from backend.database.redis_client import redis_client
from ....core.config import settings
from ....core.database import get_db
from ....core.redis import get_redis_client
from ....database.sсhemas.user import UserCreate, BaseUser, Token, UserLogin, UserProfile, UserOut
from ....core.security import create_access_token, authenticate_user, get_current_user, oauth2_scheme
from ....crud.user import crud_user


router = APIRouter(tags=["authentication"])

@router.post("/register", response_model=UserOut)
async def register(
        user_data: UserCreate,
        db: AsyncSession = Depends(get_db),
) -> UserOut:
    if await crud_user.get_by_email(db, email=user_data.email):
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )


    if await crud_user.get_by_username(db, user_data.username):
        raise HTTPException(
            status_code=400,
            detail="Username already taken"
        )
    user_db = await crud_user.create_user(user_data, db)
    await crud_user.create_base_profile(user_db.id)

    await db.commit()
    await db.refresh(user_db)

    return user_db


@router.post("/login", response_model=Token)
async def login(
        form_data: UserLogin,
        db: AsyncSession = Depends(get_db),
):
    user = await crud_user.authenticate(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "user_id": user.id},
        expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserProfile)
async def read_users_me(
        current_user: UserProfile = Depends(get_current_user),
) -> UserProfile:
    return current_user


@router.post("/logout")
async def logout(
        token: str = Security(oauth2_scheme),
        current_user: BaseUser = Depends(get_current_user),
        redis_client: Redis = Depends(get_redis_client)
):


    from datetime import datetime, timedelta
    import jwt

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        exp = payload.get("exp")
        if exp:
            ttl = exp - int(datetime.utcnow().timestamp())
            if ttl > 0:
                await redis_client.setex(f"blacklist:{token}", ttl, "true")
    except jwt.ExpiredSignatureError:
        pass
