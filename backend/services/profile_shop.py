import io
import re
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from backend.database.models.profile_shop import PointEvent, ProfileShopItem, ProfileShopOwnership
from backend.services import avatars
from backend.services.points import balance, lock_profile

MEDIA_PREFIX = "/media/avatars/"
SHOP_ASSET = re.compile(r"shop-[a-z0-9-]{1,100}\.(?:gif|webp|png|jpg)")
THEME = "profile_theme"


def asset_url(item):
    if not item.asset or not SHOP_ASSET.fullmatch(item.asset):
        return None
    path = avatars.AVATAR_DIR / item.asset
    try:
        if not path.is_symlink() and path.is_file() and 0 < path.stat().st_size <= avatars.MAX_BYTES:
            return MEDIA_PREFIX + item.asset
    except OSError:
        pass
    return None


async def catalog(db, user_id):
    rows = (await db.execute(select(ProfileShopItem, ProfileShopOwnership.item_id)
                             .outerjoin(ProfileShopOwnership, (ProfileShopOwnership.item_id == ProfileShopItem.id)
                                        & (ProfileShopOwnership.user_id == user_id))
                             .order_by(ProfileShopItem.price, ProfileShopItem.id))).all()
    items = []
    for item, owned_id in rows:
        url = asset_url(item)
        if item.kind == THEME or url:
            items.append({"id": item.id, "kind": item.kind, "name": item.name, "price": item.price,
                          "asset_url": url, "owned": owned_id is not None})
    return {"balance": await balance(db, user_id), "items": items}


async def find_item(db, item_id):
    item = (await db.execute(select(ProfileShopItem).where(ProfileShopItem.id == item_id))).scalar_one_or_none()
    if item is None or (item.kind != THEME and asset_url(item) is None):
        raise HTTPException(404, "Предмет недоступен")
    return item


async def owns_item(db, user_id, item_id):
    result = await db.execute(select(ProfileShopOwnership.item_id).where(
        ProfileShopOwnership.user_id == user_id, ProfileShopOwnership.item_id == item_id))
    return result.scalar_one_or_none() is not None


async def buy_item(db, user_id, item_id):
    await lock_profile(db, user_id)
    item = await find_item(db, item_id)
    points = await balance(db, user_id)
    if await owns_item(db, user_id, item_id):
        return {"balance": points}
    if points < item.price:
        raise HTTPException(409, "Недостаточно баллов")
    db.add(ProfileShopOwnership(user_id=user_id, item_id=item_id))
    db.add(PointEvent(user_id=user_id, key=f"purchase:{item_id}", delta=-item.price))
    await db.commit()
    return {"balance": points - item.price}


def remove_custom_background(url, user_id):
    prefix = f"{MEDIA_PREFIX}bg-{user_id}-"
    if url and url.startswith(prefix) and re.fullmatch(r"[0-9a-f]{32}\.webp", url[len(prefix):]):
        try:
            (avatars.AVATAR_DIR / url.removeprefix(MEDIA_PREFIX)).unlink(missing_ok=True)
        except OSError:
            pass


async def equip_item(db, user_id, kind, item_id):
    profile = await lock_profile(db, user_id)
    value = None
    if item_id is not None:
        item = await find_item(db, item_id)
        if item.kind != kind or not await owns_item(db, user_id, item_id):
            raise HTTPException(403, "Сначала купите предмет нужного типа")
        value = item.id if kind == THEME else asset_url(item)
    previous = getattr(profile, kind)
    setattr(profile, kind, value)
    await db.commit()
    if kind != THEME and previous != value:
        await run_in_threadpool(remove_custom_background, previous, user_id)
    return profile


def normalize_background(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"} or getattr(image, "is_animated", False):
                raise ValueError
            if max(image.size) > 4096 or image.width * image.height > 16_000_000:
                raise ValueError
            image = ImageOps.exif_transpose(image).convert("RGBA")
            image.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
            image.info.clear()
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=85)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(400, "Нужна статичная картинка JPEG, PNG или WebP до 4096 × 4096 пикселей.") from None


async def save_background(db, user_id, kind, image):
    if len(image) > avatars.MAX_BYTES:
        raise HTTPException(413, "Размер фона не должен превышать 2 МБ.")
    profile = await lock_profile(db, user_id)
    previous = getattr(profile, kind)
    filename = f"bg-{user_id}-{uuid4().hex}.webp"
    path = avatars.AVATAR_DIR / filename
    try:
        await run_in_threadpool(path.write_bytes, image)
        setattr(profile, kind, MEDIA_PREFIX + filename)
        await db.commit()
    except Exception as error:
        await db.rollback()
        await run_in_threadpool(remove_custom_background, MEDIA_PREFIX + filename, user_id)
        if isinstance(error, OSError):
            raise HTTPException(503, "Не удалось сохранить фон. Попробуйте позже.") from None
        raise
    await run_in_threadpool(remove_custom_background, previous, user_id)
    return profile
