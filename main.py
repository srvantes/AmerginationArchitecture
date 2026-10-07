import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.v1.endpoints import anime, authentication, profile, reviews, users
from backend.core.redis import close_redis


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

if __name__ == "__main__":
    uvicorn.run("main:app", port=8080, reload=True)

