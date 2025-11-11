import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from backend.api.v1.endpoints import authentication
app = FastAPI(title="Amergination API")


@app.get("/")
async def root():
    return {"message": "Hello World"}


app.include_router(authentication.router, prefix="/api/v1/auth",tags=["authentication"])


if __name__ == "__main__":
    uvicorn.run("main:app", port=8080, reload=True)

