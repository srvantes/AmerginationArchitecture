import asyncio
from backend.core.database import engine, Base
from backend.database.models.user import User

async def reset_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Таблицы пересозданы!")

if __name__ == "__main__":
    asyncio.run(reset_db())