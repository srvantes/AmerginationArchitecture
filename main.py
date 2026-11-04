import uvicorn
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Path as ApiPath, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.v1.endpoints import anime, authentication, profile, reviews, users
from backend.api.v1.endpoints import comments
from backend.api.v1.endpoints import playback_history
from backend.core.redis import close_redis
from backend.services.avatars import AVATAR_DIR
from backend.services import health
from backend.services.anime_urls import parse_anime_key
from backend.services.catalog_service import legacy_anime_path


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_redis()


app = FastAPI(lifespan=lifespan, title="Amergination")


@app.get("/health/live", tags=["health"])
async def health_live():
    return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})


@app.get("/health/ready", tags=["health"])
async def health_ready():
    checks = await health.readiness_checks()
    ready = all(checks.values())
    return JSONResponse(
        {"status": "ok" if ready else "unavailable", "checks": checks},
        status_code=200 if ready else 503, headers={"Cache-Control": "no-store"},
    )


@app.middleware("http")
async def private_playback_history_responses(request, call_next):
    response = await call_next(request)
    prefix = "/api/v1/users/me/playback-history"
    if request.url.path == prefix or request.url.path.startswith(prefix + "/"):
        response.headers["Cache-Control"] = "private, no-store"
    return response


app.include_router(authentication.router, prefix="/api/v1/auth", tags=["authentication"])
app.include_router(playback_history.router, prefix="/api/v1/users/me/playback-history")
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(anime.router, prefix="/api/v1/anime", tags=["anime"])
app.include_router(profile.router, prefix="/api/v1/profile", tags=["profile"])
app.include_router(reviews.router, prefix="/api/v1/reviews", tags=["reviews"])
app.include_router(comments.router, prefix="/api/v1/comments", tags=["comments"])

STATIC_DIR = Path(__file__).parent / "backend" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media/avatars", StaticFiles(directory=AVATAR_DIR), name="avatars")


@app.get("/", include_in_schema=False)
@app.get("/my-list", include_in_schema=False)
@app.get("/profile", include_in_schema=False)
@app.get("/profile/{profile_id}", include_in_schema=False)
@app.get("/profile/{profile_id}/list", include_in_schema=False)
@app.get("/collections/{collection_slug}", include_in_schema=False)
async def frontend(profile_id: str | None = None, collection_slug: str | None = None):
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/anime/{source}/{anime_id}", include_in_schema=False)
async def legacy_anime_frontend(source: Literal["shikimori", "animego"],
                                anime_id: str = ApiPath(pattern=r"^[1-9][0-9]{0,19}$"),
                                slug: str | None = Query(None, max_length=300)):
    return RedirectResponse(await legacy_anime_path(source, anime_id, slug), status_code=301)


@app.get("/anime/{anime_key}", include_in_schema=False)
async def anime_frontend(anime_key: str, slug: str | None = Query(None, max_length=300)):
    if parse_anime_key(anime_key):
        return await frontend()
    if re.fullmatch(r"[1-9][0-9]{0,19}", anime_key):
        # Original /anime/123 links used the AnimeGo ID namespace.
        return RedirectResponse(await legacy_anime_path("animego", anime_key, slug), status_code=301)
    raise HTTPException(404, "Страница аниме не найдена")


@app.get("/watch", include_in_schema=False)
async def watch():
    return FileResponse(Path(__file__).parent / "backend" / "static" / "watch.html")


if __name__ == "__main__":
    uvicorn.run("main:app", port=8080, reload=True)

