"""Run against real PostgreSQL and Redis; isolate SQL in a temporary schema.

Usage from the repository root: python -m scripts.check_infrastructure
"""
import asyncio
from uuid import uuid4

import httpx
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.redis import close_redis, redis_client
from backend.core.security import decode_access_token
from main import app


def apply_migrations(connection):
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    with Operations.context(MigrationContext.configure(connection)):
        for revision in reversed(list(scripts.walk_revisions())):
            revision.module.upgrade()


async def check():
    engine = create_async_engine(
        settings.DATABASE_URL, poolclass=NullPool,
        connect_args={"timeout": 3, "command_timeout": 10},
    )
    schema = "integration_" + uuid4().hex
    key = "integration:cache:" + uuid4().hex
    cleanup_keys = [key]
    schema_created = False
    scoped_engine = None
    overrides = app.dependency_overrides.copy()
    try:
        database_ok = False
        redis_ok = False
        if not all([settings.POSTGRES_USER, settings.POSTGRES_PASSWORD, settings.POSTGRES_DB]):
            print("PostgreSQL: configure POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB in .env")
        else:
            try:
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                database_ok = True
                print("PostgreSQL: connected")
            except Exception as exc:
                print(f"PostgreSQL: connection failed ({type(exc).__name__})")
        try:
            redis_ok = bool(await redis_client.ping())
            print("Redis: connected" if redis_ok else "Redis: ping failed")
        except Exception as exc:
            print(f"Redis: connection failed ({type(exc).__name__})")
        if not database_ok or not redis_ok:
            print("Integration scenario skipped: both services must be available.")
            return 2

        # The identifier consists solely of this script's prefix and UUID hex.
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        schema_created = True
        scoped_engine = create_async_engine(
            settings.DATABASE_URL, poolclass=NullPool,
            connect_args={"timeout": 3, "command_timeout": 10,
                          "server_settings": {"search_path": schema}},
        )
        async with scoped_engine.begin() as connection:
            await connection.run_sync(apply_migrations)
        print("Migrations: applied in temporary schema")
        sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)

        async def integration_db():
            async with sessions() as session:
                try:
                    yield session
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db] = integration_db
        await redis_client.setex(key, 60, "ok")
        if await redis_client.get(key) not in {"ok", b"ok"}:
            raise RuntimeError("Redis read/write verification failed")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://integration",
        ) as client:
            async def request(method, path, expected, **kwargs):
                response = await client.request(method, path, **kwargs)
                if response.status_code != expected:
                    raise RuntimeError(f"{method} {path}: expected {expected}, got {response.status_code}")
                return response

            name = "integration_" + uuid4().hex[:12]
            await request("POST", "/api/v1/auth/register", 201, json={
                "username": name, "email": f"{name}@example.com",
                "password": "integration-test-password",
            })
            response = await request("POST", "/api/v1/auth/login", 200, json={
                "username": name, "password": "integration-test-password",
            })
            token = response.json()["access_token"]
            cleanup_keys.append("revoked-token:" + decode_access_token(token)["jti"])
            headers = {"Authorization": f"Bearer {token}"}
            await request("GET", "/api/v1/auth/me", 200, headers=headers)
            await request("PATCH", "/api/v1/profile/settings", 200, headers=headers,
                          json={"nickname": "Integration check"})
            anime = {"anime_external_id": "20", "anime_title": "Naruto"}
            response = await request("POST", "/api/v1/users/me/watchlist", 201,
                                     headers=headers, json=anime)
            entry_id = response.json()["id"]
            await request("PATCH", f"/api/v1/users/me/watchlist/{entry_id}", 200,
                          headers=headers, json={"status": "watching", "episodes_watched": 3})
            response = await request("GET", "/api/v1/users/me/watchlist", 200, headers=headers)
            if len(response.json()) != 1 or response.json()[0]["episodes_watched"] != 3:
                raise RuntimeError("Watchlist persistence verification failed")
            await request("POST", "/api/v1/reviews/", 201, headers=headers,
                          json={**anime, "text": "Integration review", "rating": 8})
            await request("POST", "/api/v1/auth/logout", 204, headers=headers)
            await request("GET", "/api/v1/auth/me", 401, headers=headers)
        print("PASS: register, login, profile, watchlist, review, logout, revoked JWT")
        return 0
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)
        if scoped_engine is not None:
            await scoped_engine.dispose()
        if schema_created:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await redis_client.delete(*cleanup_keys)
        await engine.dispose()
        await close_redis()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check()))
