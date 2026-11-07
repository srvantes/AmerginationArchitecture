"""Decode uploaded images and store only resized PNGs with generated names."""
import io
import re
import warnings
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, Request
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from backend.database.models.user import UserProfile

AVATAR_DIR = Path(__file__).resolve().parents[2] / "var" / "avatars"
MAX_BYTES = 2 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


def normalize_image(data: bytes) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"} or getattr(image, "is_animated", False):
                    raise ValueError
                if max(image.size) > 4096 or image.width * image.height > 16_000_000:
                    raise ValueError
                image.load()
                cropped = ImageOps.fit(ImageOps.exif_transpose(image).convert("RGBA"), (256, 256))
                # A fresh image removes EXIF, comments and other source metadata.
                clean = Image.new("RGBA", (256, 256))
                clean.paste(cropped)
                output = io.BytesIO()
                clean.save(output, format="PNG")
                return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(400, "Нужна статичная картинка JPEG, PNG или WebP до 4096 × 4096 пикселей.") from None


async def read_image_upload(request: Request, size_error: str) -> bytes:
    if request.headers.get("content-type", "").split(";", 1)[0].lower() not in ALLOWED_TYPES:
        raise HTTPException(415, "Поддерживаются JPEG, PNG и WebP.")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, size_error)
        data.extend(chunk)
    return bytes(data)


async def read_image(request: Request) -> bytes:
    data = await read_image_upload(request, "Размер аватара не должен превышать 2 МБ.")
    return await run_in_threadpool(normalize_image, data)


def remove_owned_avatar(url: str | None, user_id) -> None:
    prefix = "/media/avatars/"
    if not url or not url.startswith(prefix):
        return
    filename = url[len(prefix):]
    if re.fullmatch(re.escape(str(user_id)) + r"-[0-9a-f]{32}\.png", filename):
        (AVATAR_DIR / filename).unlink(missing_ok=True)


async def save_avatar(db, user_id, image: bytes) -> UserProfile:
    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id)
                              .with_for_update().execution_options(populate_existing=True))
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(404, "Профиль не найден.")
    filename = f"{user_id}-{uuid4().hex}.png"
    path = AVATAR_DIR / filename
    old_url = profile.avatar_url
    try:
        await run_in_threadpool(path.write_bytes, image)
        profile.avatar_url = "/media/avatars/" + filename
        await db.commit()
    except Exception as error:
        await db.rollback()
        try:
            await run_in_threadpool(path.unlink, missing_ok=True)
        except OSError:
            pass
        if isinstance(error, OSError):
            raise HTTPException(503, "Не удалось сохранить аватар. Попробуйте позже.") from None
        raise
    # Cleanup must not turn a committed update into an apparent failed upload.
    try:
        await run_in_threadpool(remove_owned_avatar, old_url, user_id)
    except OSError:
        pass
    await db.refresh(profile)
    return profile
