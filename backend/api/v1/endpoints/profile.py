from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.core.rate_limit import RATE_LIMIT_RESPONSES, limited_avatar_upload, limited_profile_edit
from backend.services.avatars import read_image, save_avatar
from backend.services.achievements import my_achievements, public_showcase, select_showcase
from backend.database.sсhemas.achievement import MyAchievement, AchievementOut, ShowcaseSelection

from backend.database.models.user import User
from backend.database.sсhemas.user import MiniProfile, PublicProfile, UserProfile as UserProfile_sh, UserProfileUpdate
from backend.crud.user import crud_user
router = APIRouter(tags=['profile'])


@router.get("/me/achievements", response_model=list[MyAchievement])
async def get_my_achievements(response: Response, user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    return await my_achievements(db, user.id)


@router.put("/me/achievements/showcase", response_model=list[AchievementOut], responses=RATE_LIMIT_RESPONSES)
async def update_showcase(data: ShowcaseSelection, response: Response,
                          user: User = Depends(limited_profile_edit), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    return await select_showcase(db, user.id, data.codes)


@router.get("/{user_id}/achievements", response_model=list[AchievementOut])
async def get_public_achievements(user_id: UUID, response: Response, db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    return await public_showcase(db, user_id)


@router.get("/{user_id}/mini", response_model=MiniProfile)
async def get_mini_profile(user_id: UUID, response: Response, db: AsyncSession = Depends(get_db)):
    profile = await get_profile(user_id, response, db)
    return MiniProfile(profile=profile, achievements=await public_showcase(db, user_id))


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

@router.get("/{user_id}", response_model=PublicProfile)
async def get_profile(
        user_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    account = await crud_user.get_by_id(db, user_id)
    if not account or not account.profile or not account.profile.is_active:
        raise HTTPException(status_code=404, detail="User not found")
    values = {field: getattr(account.profile, field) for field in PublicProfile.model_fields
              if field not in {"id", "username"}}
    return PublicProfile(id=account.id, username=account.username, **values)

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
