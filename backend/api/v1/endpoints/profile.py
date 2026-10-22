from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.core.rate_limit import RATE_LIMIT_RESPONSES, limited_avatar_upload, limited_profile_edit
from backend.services.avatars import read_image, save_avatar

from backend.database.models.user import User
from backend.database.sсhemas.user import UserProfile as UserProfile_sh, UserProfileUpdate
from backend.crud.user import crud_user
router = APIRouter(tags=['profile'])


@router.post("/avatar", response_model=UserProfile_sh,
             responses={**RATE_LIMIT_RESPONSES, 400: {"description": "Некорректная картинка"},
                        413: {"description": "Картинка больше 2 МБ"}, 415: {"description": "Неподдерживаемый формат"}},
             openapi_extra={"requestBody": {"required": True, "content": {
                 mime: {"schema": {"type": "string", "format": "binary"}}
                 for mime in ("image/jpeg", "image/png", "image/webp")}}})
async def upload_avatar(
        request: Request,
        user: User = Depends(limited_avatar_upload),
        db: AsyncSession = Depends(get_db),
):
    image = await read_image(request)
    return await save_avatar(db, user.id, image)

@router.get("/{user_id}", response_model=UserProfile_sh)
async def get_profile(
        user_id: UUID,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    user_profile = await crud_user.get_user_profile(db, user_id)
    if not user_profile:
        raise HTTPException(status_code=404, detail="User not found")
    return user_profile

@router.patch("/settings", response_model=UserProfile_sh, responses=RATE_LIMIT_RESPONSES)
async def update_profile(
        profile_data: UserProfileUpdate,
        user: User = Depends(limited_profile_edit),
        db: AsyncSession = Depends(get_db),

) -> UserProfile_sh:

    try:
        updated_profile = await crud_user.update_profile(db, user.id, profile_data)
        return updated_profile
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Custom URL already taken")
