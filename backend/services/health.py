"""Small local dependency probes with a shared response deadline."""
import asyncio

from sqlalchemy import text

from backend.core.database import engine
from backend.core.redis import redis_client


READINESS_TIMEOUT_SECONDS = 3.0
_cleaning_probes: set[asyncio.Task] = set()


async def check_database() -> bool:
    async with engine.connect() as connection:
        return await connection.scalar(text("SELECT 1")) == 1


async def check_redis() -> bool:
    return await redis_client.ping() is True


def _probe_finished(task):
    _cleaning_probes.discard(task)
    if not task.cancelled():
        # Consume failures without logging credentials embedded in driver errors.
        task.exception()


async def readiness_checks() -> dict[str, bool]:
    tasks = {
        "database": asyncio.create_task(check_database()),
        "redis": asyncio.create_task(check_redis()),
    }
    try:
        await asyncio.wait(tasks.values(), timeout=READINESS_TIMEOUT_SECONDS)
        checks = {}
        for name, task in tasks.items():
            try:
                checks[name] = task.done() and not task.cancelled() and task.result() is True
            except Exception:
                checks[name] = False
        return checks
    finally:
        for task in tasks.values():
            if not task.done():
                # Cancellation can trigger asynchronous driver cleanup. Let it
                # finish without extending the HTTP response beyond our deadline.
                _cleaning_probes.add(task)
                task.cancel()
            task.add_done_callback(_probe_finished)
