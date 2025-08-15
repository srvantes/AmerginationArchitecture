import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
app = FastAPI(title="Amergination Architecture")


@app.get("/")
async def root():
    return {"message": "Hello World"}





if __name__ == "__main__":
    uvicorn.run("main:app", port=8080, reload=True)

