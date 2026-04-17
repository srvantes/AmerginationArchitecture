import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from backend.api.v1.endpoints import authentication, users, anime, news, profile, reviews

app = FastAPI(title="Amergination")




app.include_router(authentication.router, prefix="/api/v1/auth",tags=["authentication"])
app.include_router(users.router, prefix="/api/v1/users",tags=["users"])

app.include_router(anime.router, prefix="/api/v1/anime",tags=["anime"])

app.include_router(profile.router, prefix="/api/v1/profile",tags=["profile"])

app.include_router(reviews.router, prefix="/api/v1/reviews",tags=["reviews"])



if __name__ == "__main__":
    uvicorn.run("main:app", port=8080, reload=True)

