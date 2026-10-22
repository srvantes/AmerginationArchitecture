"""Check one-time recovery under concurrent real PostgreSQL transactions.

python -m scripts.check_password_reset
Uses and deletes an isolated temporary schema. Never sends emails.
"""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from backend.core.config import settings
from backend.core.password import get_password_hash, verify_password
from backend.database.models.user import User, UserProfile
from backend.crud.user import crud_user
from backend.services import password_reset as service
from scripts.check_infrastructure import apply_migrations


async def main():
    assert settings.POSTGRES_HOST in {"localhost", "127.0.0.1", "::1"}, "Local development database only"
    schema = "test_pwd_" + uuid4().hex
    control = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    scoped = None
    created = False
    try:
        async with control.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        scoped = create_async_engine(settings.DATABASE_URL, poolclass=NullPool,
            connect_args={"server_settings": {"search_path": schema}, "timeout": 3, "command_timeout": 10})
        async with scoped.begin() as connection:
            await connection.run_sync(apply_migrations)
        sessions = async_sessionmaker(scoped, expire_on_commit=False)
        user_id = uuid4()
        async with sessions() as db:
            user = User(id=user_id, username="recovery_test", email="recovery@example.com",
                        hashed_password=get_password_hash("old-test-password"), email_verified_at=datetime.now(timezone.utc),
                        profile=UserProfile(id=user_id))
            db.add(user); await db.commit()
            with patch.object(service.secrets, "randbelow", return_value=1234):
                # BackgroundTasks is deliberately never executed: no SMTP messages.
                await service.request_reset(db, user, BackgroundTasks())

        async def verify():
            async with sessions() as db:
                user = await crud_user.get_by_id(db, user_id)
                try:
                    return await service.verify_code(db, user, "001234")
                except HTTPException as error:
                    return error.status_code
        results = await asyncio.gather(verify(), verify())
        successes = [result for result in results if isinstance(result, dict)]
        assert len(successes) == 1 and results.count(400) == 1, "Code redeemed more than once"
        ticket = successes[0]["reset_token"]

        async def finish():
            async with sessions() as db:
                try:
                    return await service.finish_reset(db, ticket, "new-test-password")
                except HTTPException as error:
                    return error.status_code
        results = await asyncio.gather(finish(), finish())
        assert sum(isinstance(result, dict) for result in results) == 1 and results.count(400) == 1, "Ticket reused"
        async with sessions() as db:
            user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
            assert user.auth_version == 1
            assert verify_password("new-test-password", user.hashed_password)
        print("PostgreSQL recovery: concurrent code redemption and password reset each succeeded exactly once")
    finally:
        if scoped:
            await scoped.dispose()
        if created:
            async with control.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await control.dispose()


if __name__ == "__main__":
    asyncio.run(main())
