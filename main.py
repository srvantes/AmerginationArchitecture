import uvicorn
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.v1.endpoints import anime, authentication, profile, reviews, users
from backend.api.v1.endpoints import comments
from backend.core.redis import close_redis
from backend.services.avatars import AVATAR_DIR


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_redis()


app = FastAPI(lifespan=lifespan, title="Amergination")

app.include_router(authentication.router, prefix="/api/v1/auth", tags=["authentication"])
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
@app.get("/anime/{anime_id}", include_in_schema=False)
@app.get("/anime/{source}/{anime_id}", include_in_schema=False)
async def frontend(anime_id: str | None = None, source: str | None = None):
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/watch", include_in_schema=False)
async def watch():
    return FileResponse(Path(__file__).parent / "backend" / "static" / "watch.html")


if __name__ == "__main__":
    uvicorn.run("main:app", port=8080, reload=True)

