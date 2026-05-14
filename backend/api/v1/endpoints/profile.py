from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user

from backend.database.models.user import User
from backend.database.sсhemas.user import UserProfile as UserProfile_sh, BaseUser, UserProfileUpdate
from backend.crud.user import crud_user
router = APIRouter(tags=['profile'])

@router.get("/profile/{user_id}", response_model=UserProfile_sh)
async def get_profile(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    user_profile = await crud_user.get_user_profile(db, user.id)
    if not user_profile:
        raise HTTPException(status_code=404, detail="User not found")
    return user_profile

@router.post("/profile/settings", response_model=UserProfile_sh)
async def update_profile(
        profile_data: UserProfileUpdate,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),

) -> UserProfile_sh:

    try:
        updated_profile = await crud_user.update_profile(db, user.id, profile_data)
        return updated_profile
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except IntegrityError as e:
        raise HTTPException(status_code=400, detail="Custom URL already taken")