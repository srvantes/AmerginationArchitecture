"""Small persistent title registry. No per-card SQL or full-catalog crawling."""
import asyncio
import logging
import re
from datetime import datetime, timezone
from time import monotonic
from typing import Literal
from weakref import WeakKeyDictionary

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from backend.core.cache import get_cached_json_many, set_cached_json_many
from backend.core.database import AsyncSessionLocal
from backend.database.models.anime_registry import AnimeRegistry
from backend.services.anime_urls import anime_path, parse_anime_key


log = logging.getLogger(__name__)
CACHE_SECONDS = 21600
BATCH_SIZE = 100
DB_TIMEOUT_SECONDS = 2
_database_pauses = WeakKeyDictionary()


class RegistryTitle(BaseModel):
    source: Literal["shikimori", "animego"]
    external_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    title: str = Field(min_length=1)
    original_title: str | None = None
    public_slug: str = Field(min_length=1, max_length=300, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    upstream_slug: str | None = Field(None, max_length=300, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    @property
    def public_path(self):
        return anime_path(self.source, self.external_id, public_slug=self.public_slug)


def _key(identity):
    return "catalog:registry:v1:" + ":".join(identity)


def _identity(source, identifier):
    path = anime_path(source, identifier)
    return (source, str(identifier)) if path else None


def _from_row(row):
    return RegistryTitle.model_validate({name: getattr(row, name) for name in RegistryTitle.model_fields})


def _same(record, fields):
    return (record.title == fields["title"]
            and (fields["original_title"] is None or record.original_title == fields["original_title"])
            and (fields["upstream_slug"] is None or record.upstream_slug == fields["upstream_slug"]))


async def _database(operation):
    loop = asyncio.get_running_loop()
    if _database_pauses.get(loop, 0) > monotonic():
        return {}
    try:
        async with asyncio.timeout(DB_TIMEOUT_SECONDS):
            async with AsyncSessionLocal() as db:
                return await operation(db)
    except (SQLAlchemyError, OSError, TimeoutError) as error:
        # A registry outage must not make the public catalog unusable. Avoid
        # paying the connection timeout again on every shelf while it is down.
        _database_pauses[loop] = monotonic() + 15
        log.warning("Anime registry temporarily unavailable (%s)", type(error).__name__)
        return {}


async def _select(db, identities):
    result = await db.execute(select(AnimeRegistry).where(
        tuple_(AnimeRegistry.source, AnimeRegistry.external_id).in_(identities)))
    return {(row.source, row.external_id): _from_row(row) for row in result.scalars().all()}


async def _save(db, fields):
    identities = sorted(fields)
    records = await _select(db, identities)
    changed = [fields[identity] for identity in identities
               if identity not in records or not _same(records[identity], fields[identity])]
    if changed:
        dialect = getattr(db, "session", db).get_bind().dialect.name
        insert = pg_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
        if insert is None:
            raise RuntimeError("Anime registry requires PostgreSQL or SQLite")
        statement = insert(AnimeRegistry).values(changed)
        statement = statement.on_conflict_do_update(
            index_elements=[AnimeRegistry.source, AnimeRegistry.external_id],
            set_={"title": statement.excluded.title,
                  "original_title": func.coalesce(statement.excluded.original_title, AnimeRegistry.original_title),
                  "upstream_slug": func.coalesce(statement.excluded.upstream_slug, AnimeRegistry.upstream_slug),
                  "updated_at": datetime.now(timezone.utc)},
            # public_slug is intentionally never changed by metadata refresh.
        ).returning(AnimeRegistry).execution_options(populate_existing=True)
        result = await db.execute(statement)
        records.update({(row.source, row.external_id): _from_row(row) for row in result.scalars().all()})
        await db.commit()
    return records


async def _cached(identities):
    raw = await get_cached_json_many([_key(identity) for identity in identities])
    records = {}
    for identity in identities:
        value = raw.get(_key(identity))
        if value is not None:
            try:
                record = RegistryTitle.model_validate(value)
                if (record.source, record.external_id) == identity:
                    records[identity] = record
            except ValidationError:
                pass
    return records


async def _cache(records):
    await set_cached_json_many({_key(identity): record.model_dump() for identity, record in records.items()}, CACHE_SECONDS)


async def lookup_titles(identities):
    identities = sorted({identity for source, identifier in identities
                         if (identity := _identity(source, identifier)) is not None})
    records = {}
    for offset in range(0, len(identities), BATCH_SIZE):
        batch = identities[offset:offset + BATCH_SIZE]
        cached = await _cached(batch)
        missing = [identity for identity in batch if identity not in cached]
        if missing:
            loaded = await _database(lambda db: _select(db, missing))
            await _cache(loaded)
            cached.update(loaded)
        records.update(cached)
    return records


async def get_title(source, identifier):
    identity = _identity(source, identifier)
    if identity is None:
        return None
    return (await lookup_titles([identity])).get(identity)


async def remember_titles(cards):
    fields = {}
    for card in cards:
        path = card.public_path
        parsed = parse_anime_key(path.removeprefix("/anime/")) if path else None
        if parsed is None:
            continue
        upstream = card.slug if card.source == "animego" else None
        if not isinstance(upstream, str) or len(upstream) > 300 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", upstream):
            upstream = None
        candidate = RegistryTitle(source=card.source, external_id=card.external_id,
                                  title=card.title, original_title=(card.original_title or "").strip() or None,
                                  public_slug=parsed["slug"],
                                  upstream_slug=upstream)
        identity = (candidate.source, candidate.external_id)
        values = candidate.model_dump()
        previous = fields.get(identity)
        if previous:
            values["original_title"] = values["original_title"] or previous["original_title"]
            values["upstream_slug"] = values["upstream_slug"] or previous["upstream_slug"]
            values["public_slug"] = previous["public_slug"]
        fields[identity] = values
    records = {}
    identities = sorted(fields)
    for offset in range(0, len(identities), BATCH_SIZE):
        batch = identities[offset:offset + BATCH_SIZE]
        cached = await _cached(batch)
        pending = {identity: fields[identity] for identity in batch
                   if identity not in cached or not _same(cached[identity], fields[identity])}
        if pending:
            loaded = await _database(lambda db: _save(db, pending))
            await _cache(loaded)
            cached.update(loaded)
        records.update(cached)
    for card in cards:
        record = records.get((card.source, card.external_id))
        if record:
            card._registry_slug = record.public_slug
