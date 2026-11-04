"""Normalize known shapes from anime-parsers-ru 1.18 at the HTTP boundary."""
import logging
import re
from functools import wraps
from urllib.parse import urljoin, urlparse

from fastapi import HTTPException
from backend.services.posters import poster_url

from backend.database.sсhemas.catalog import (
    AnimeCard, AnimeDetails, Episode, EpisodeList, PlayerInfo,
    StreamInfo, StreamVariant, Translation, EmbeddedPlayer,
)

logger = logging.getLogger(__name__)


def adapter(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            logger.exception("Invalid upstream payload in %s", func.__name__)
            raise HTTPException(status_code=502, detail="External service returned an invalid response")
    return wrapped


def text(value):
    return str(value).strip() if value is not None else None


def required_text(value):
    result = text(value)
    if not result:
        raise ValueError("Required upstream field is missing")
    return result


def number(value, kind=int):
    if value is None or str(value).strip() in {"", "?", "-", "—"}:
        return None
    try:
        return kind(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def url(value, base=None):
    value = text(value)
    if not value:
        return None
    if value.startswith("//"):
        return "https:" + value
    return urljoin(base, value) if base else value


def shikimori_id(link):
    match = re.fullmatch(r"/animes/[a-z]*([0-9]+)(?:-[^/]*)?/?", urlparse(link).path)
    if not match:
        raise ValueError("Invalid anime path")
    return match.group(1)


@adapter
def anime_card(data, source):
    if source == "shikimori":
        external_id = required_text(data.get("shikimori_id"))
        poster = data.get("poster")
        base = "https://shikimori.io"
        slug = None
        score = data.get("score")
    else:
        external_id = required_text(data.get("id"))
        poster = data.get("image")
        base = "https://animego.org"
        slug = text(data.get("slug"))
        score = data.get("rating")
    return AnimeCard(
        source=source, external_id=external_id,
        title=required_text(data.get("title")),
        original_title=text(data.get("original_title")),
        page_url=url(data.get("link"), base), poster_url=poster_url(poster, base),
        slug=slug, year=number(data.get("year")), kind=text(data.get("type")),
        status=text(data.get("status")), studio=text(data.get("studio")),
        genres=data.get("genres") or [], score=number(score, float),
    )


@adapter
def anime_details(data, link):
    external_id = shikimori_id(link)
    card = anime_card({**data, "shikimori_id": external_id, "link": link,
                       "poster": data.get("picture")}, "shikimori")
    episodes_text = text(data.get("episodes"))
    parts = episodes_text.split("/") if episodes_text else []
    aired = number(parts[0]) if len(parts) == 2 else None
    total = number(parts[-1]) if parts else None
    return AnimeDetails(
        **card.model_dump(), description=text(data.get("description")),
        episodes_total=total, episodes_aired=aired, episodes_text=episodes_text,
        episode_duration=text(data.get("episode_duration")),
        next_episode=text(data.get("next_episode")), dates=text(data.get("dates")),
        age_rating=text(data.get("rating")), themes=data.get("themes") or [],
        licensed=text(data.get("licensed")), licensed_in_ru=text(data.get("licensed_in_ru")),
        premiere_in_ru=text(data.get("premiere_in_ru")),
    )


@adapter
def episode_list(data, external_id):
    return EpisodeList(
        source="animego", external_id=external_id,
        episodes=[Episode(number=item["seria"], title=text(item.get("title")),
                          air_date=text(item.get("air_date")),
                          is_released=item.get("is_released"))
                  for item in data],
    )


@adapter
def player_info(data, source, external_id):
    translations = []
    for item in data["voices" if source == "animego" else "translations"]:
        start, end = None, None
        if item.get("series_range") is not None:
            start, end = item["series_range"]
        translations.append(Translation(
            id=required_text(item.get("translation_id") if source == "animego" else item.get("id")),
            name=required_text(item.get("label") if source == "animego" else item.get("name")),
            player=text(item.get("player")).lower() if item.get("player") else ("kodik" if source == "kodik" else None),
            kind=text(item.get("type")), embed_url=url(item.get("embed")),
            episodes_start=start, episodes_end=end,
        ))
    return PlayerInfo(
        source=source, external_id=external_id,
        id_source="shikimori" if source == "kodik" else source,
        episodes_total=number(data.get("series_count") if source == "kodik" else data.get("total_episodes")),
        translations=translations,
    )


@adapter
def embedded_player(voice, external_id, episode):
    return EmbeddedPlayer(
        source="animego", external_id=external_id, episode=episode,
        translation_id=required_text(voice.get("translation_id")),
        translation_name=required_text(voice.get("label")),
        player=required_text(voice.get("player")).lower(),
        embed_url=url(voice.get("embed")),
    )


@adapter
def stream_info(data, source, external_id, episode, translation_id):
    variants = []
    if source == "kodik":
        variants.append(StreamVariant(url=url(data["stream_url"]), format="hls", quality=data.get("quality")))
        player = "kodik"
    else:
        player = required_text(data.get("player")).lower()
        if player == "cvh":
            for field, format_name in [("hls", "hls"), ("dash", "dash")]:
                if data.get(field):
                    variants.append(StreamVariant(url=url(data[field]), format=format_name))
            for link in data.get("mp4") or []:
                variants.append(StreamVariant(url=url(link), format="mp4"))
        else:
            format_name = {"HLS": "hls", "MPD": "dash", "DASH": "dash"}.get(str(data.get("kind")).upper())
            if format_name is None:
                raise ValueError("Unknown stream format")
            variants.append(StreamVariant(url=url(data.get("url")), format=format_name))
    return StreamInfo(
        source=source, external_id=external_id,
        id_source="shikimori" if source == "kodik" else source,
        episode=episode, translation_id=translation_id,
        translation_name=text(data.get("translation")), player=player, streams=variants,
    )
