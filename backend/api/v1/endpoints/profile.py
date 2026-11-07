from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.core.rate_limit import RATE_LIMIT_RESPONSES, limited_avatar_upload, limited_profile_edit
from backend.services.avatars import ALLOWED_TYPES, read_image, read_image_upload, save_avatar
from backend.services.profile_shop import buy_item, catalog, equip_item, normalize_background, save_background
from backend.services.achievements import my_achievements, public_showcase, select_showcase
from backend.database.sсhemas.achievement import MyAchievement, AchievementOut, ShowcaseSelection

from backend.database.models.user import User
from backend.database.sсhemas.user import MiniProfile, PublicProfile, UserProfile as UserProfile_sh, UserProfileUpdate
from backend.crud.user import crud_user
router = APIRouter(tags=['profile'])
BackgroundKind = Literal["profile_background", "mini_profile_background"]


class ShopSelection(BaseModel):
    kind: Literal["profile_background", "mini_profile_background", "profile_theme"]
    item_id: str | None = Field(max_length=40)


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


@router.get("/shop")
async def get_shop(response: Response, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    return await catalog(db, user.id)


@router.post("/shop/{item_id}/buy", responses=RATE_LIMIT_RESPONSES)
async def purchase(item_id: str, user: User = Depends(limited_profile_edit), db: AsyncSession = Depends(get_db)):
    return await buy_item(db, user.id, item_id)


@router.put("/shop/equip", response_model=UserProfile_sh, responses=RATE_LIMIT_RESPONSES)
async def equip(data: ShopSelection, user: User = Depends(limited_profile_edit), db: AsyncSession = Depends(get_db)):
    return await equip_item(db, user.id, data.kind, data.item_id)


@router.put("/background/{kind}", response_model=UserProfile_sh, responses=RATE_LIMIT_RESPONSES,
            openapi_extra={"requestBody": {"required": True, "content": {
                mime: {"schema": {"type": "string", "format": "binary"}} for mime in sorted(ALLOWED_TYPES)}}})
async def upload_background(kind: BackgroundKind, request: Request, user: User = Depends(limited_avatar_upload),
                            db: AsyncSession = Depends(get_db)):
    data = await read_image_upload(request, "Размер фона не должен превышать 2 МБ.")
    image = await run_in_threadpool(normalize_background, data)
    return await save_background(db, user.id, kind, image)


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
