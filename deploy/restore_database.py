"""Prepare/switch a restored database without deleting the previous database.

Run only inside the app image of the selected production Compose project.
Database credentials come exclusively from that container's environment.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from uuid import uuid4

import asyncpg


STAGING_PREFIX = "amergination_restore_"
PREVIOUS_PREFIX = "amergination_previous_"


class RestoreError(ValueError):
    pass


def identifier(value: str) -> str:
    """Quote an entire SQL identifier; values never enter SQL as fragments."""
    if not isinstance(value, str) or not value or "\0" in value or len(value.encode("utf-8")) > 63:
        raise RestoreError("Invalid database/user identifier.")
    return '"' + value.replace('"', '""') + '"'


def configured_target() -> tuple[str, str]:
    target = os.environ.get("POSTGRES_DB", "")
    user = os.environ.get("POSTGRES_USER", "")
    identifier(target)
    identifier(user)
    if target in {"postgres", "template0", "template1"}:
        raise RestoreError("The application database must not be a PostgreSQL maintenance/template database.")
    if os.environ.get("POSTGRES_HOST") != "postgres" or os.environ.get("POSTGRES_PORT", "5432") != "5432":
        raise RestoreError("Database restore must run against the selected Compose postgres service.")
    return target, user


async def target_state(connection, target: str, user: str):
    row = await connection.fetchrow(
        "SELECT oid, datname, datallowconn, pg_get_userbyid(datdba) AS owner "
        "FROM pg_database WHERE datname = $1", target,
    )
    if row is None or row["owner"] != user:
        raise RestoreError("The configured application database must exist and belong to the configured PostgreSQL user.")
    return row


async def prepare(connection, target: str, user: str) -> tuple[str, str]:
    await target_state(connection, target, user)
    suffix = uuid4().hex
    staging, previous = STAGING_PREFIX + suffix, PREVIOUS_PREFIX + suffix
    # CREATE DATABASE must run outside a transaction. template0 excludes any
    # extra objects installed in template1 or in the current application DB.
    await connection.execute(f"CREATE DATABASE {identifier(staging)} TEMPLATE template0 OWNER {identifier(user)}")
    await connection.execute(f"REVOKE CONNECT ON DATABASE {identifier(staging)} FROM PUBLIC")
    return staging, previous


async def switch(connection, target: str, user: str, staging: str, previous: str) -> None:
    suffix = staging.removeprefix(STAGING_PREFIX)
    if (not staging.startswith(STAGING_PREFIX) or not re.fullmatch(r"[0-9a-f]{32}", suffix)
            or previous != PREVIOUS_PREFIX + suffix or target in {staging, previous}):
        raise RestoreError("Invalid staging/rollback database pair.")
    original = await target_state(connection, target, user)
    replacement = await target_state(connection, staging, user)
    if await connection.fetchval("SELECT EXISTS (SELECT FROM pg_database WHERE datname = $1)", previous):
        raise RestoreError("The rollback database name already exists.")
    original_flags = {target: original["datallowconn"], staging: replacement["datallowconn"]}
    try:
        # Commit the connection blocks before terminating existing sessions;
        # otherwise another connection could slip in between terminate/rename.
        await connection.execute(f"ALTER DATABASE {identifier(target)} ALLOW_CONNECTIONS false")
        await connection.execute(f"ALTER DATABASE {identifier(staging)} ALLOW_CONNECTIONS false")
        await connection.fetch(
            "SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity "
            "WHERE datname = ANY($1::text[]) AND pid <> pg_backend_pid()", [target, staging],
        )
        # Both names change in the same transaction. A failed second rename
        # rolls back the first, leaving the existing application DB in place.
        async with connection.transaction():
            await connection.execute("SET LOCAL lock_timeout = '10s'")
            await connection.execute(f"ALTER DATABASE {identifier(target)} RENAME TO {identifier(previous)}")
            await connection.execute(f"ALTER DATABASE {identifier(staging)} RENAME TO {identifier(target)}")
            await connection.execute(f"ALTER DATABASE {identifier(target)} ALLOW_CONNECTIONS true")
    except Exception:
        # Recover availability flags only when database OIDs prove that the
        # names did not switch. An ambiguous/disconnected commit must never
        # mutate whichever database happens to occupy a name afterward.
        try:
            rows = await connection.fetch("SELECT oid, datname FROM pg_database WHERE oid = ANY($1::oid[])",
                                          [original["oid"], replacement["oid"]])
            names = {row["oid"]: row["datname"] for row in rows}
            if names.get(original["oid"]) == target and names.get(replacement["oid"]) == staging:
                for name, allowed in original_flags.items():
                    await connection.execute(f"ALTER DATABASE {identifier(name)} ALLOW_CONNECTIONS {'true' if allowed else 'false'}")
        except Exception:
            pass
        raise


async def run(arguments: list[str]) -> None:
    target, user = configured_target()
    connection = await asyncpg.connect(
        host="postgres", port=5432, user=user, password=os.environ.get("POSTGRES_PASSWORD"), database="postgres",
        timeout=10, command_timeout=30, server_settings={"application_name": "amergination-restore"},
    )
    try:
        if arguments == ["prepare"]:
            staging, previous = await prepare(connection, target, user)
            # Only generated non-secret identifiers go to stdout, parsed by Bash.
            print(staging, previous, flush=True)
        elif len(arguments) == 3 and arguments[0] == "switch":
            await switch(connection, target, user, arguments[1], arguments[2])
        else:
            raise RestoreError("Usage: restore_database.py prepare|switch STAGING PREVIOUS")
    finally:
        await connection.close()


def main() -> int:
    try:
        asyncio.run(run(sys.argv[1:]))
    except Exception as error:
        # asyncpg exceptions can include connection diagnostics. Log neither
        # those values nor a DSN/password; the shell keeps the site stopped.
        message = str(error) if isinstance(error, RestoreError) else type(error).__name__
        print("Database restore operation failed: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
