"""Public API contracts, independent of parser field names."""
from enum import IntEnum
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field, PrivateAttr, computed_field

from .anime import AnimeSource
from backend.services.anime_urls import anime_path


class StreamQuality(IntEnum):
    Q360 = 360
    Q480 = 480
    Q720 = 720
    Q1080 = 1080


class EmbeddedPlayer(BaseModel):
    source: AnimeSource
    external_id: str
    episode: int = Field(ge=1)
    translation_id: str
    translation_name: str
    player: str
    embed_url: AnyHttpUrl


class AnimeCard(BaseModel):
    _registry_slug: str | None = PrivateAttr(default=None)
    source: AnimeSource
    external_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    original_title: str | None = None
    page_url: AnyHttpUrl | None = None
    poster_url: AnyHttpUrl | None = None
    slug: str | None = None
    year: int | None = None
    kind: str | None = None
    status: str | None = None
    studio: str | None = None
    genres: list[str] = Field(default_factory=list)
    score: float | None = Field(None, ge=0, le=10)

    @computed_field
    @property
    def public_path(self) -> str | None:
        return anime_path(self.source, self.external_id, self.title, self.original_title, self.slug,
                          public_slug=self._registry_slug)


class AnimeDetails(AnimeCard):
    description: str | None = None
    episodes_total: int | None = Field(None, ge=0)
    episodes_aired: int | None = Field(None, ge=0)
    episodes_text: str | None = None
    episode_duration: str | None = None
    next_episode: str | None = None
    dates: str | None = None
    age_rating: str | None = None
    themes: list[str] = Field(default_factory=list)
    licensed: str | None = None
    licensed_in_ru: str | None = None
    premiere_in_ru: str | None = None


class RelatedAnime(AnimeCard):
    relation: str | None = None


class PlaybackMatch(BaseModel):
    status: Literal["matched", "not_found", "ambiguous", "unavailable", "pending"]
    animego_id: str | None = None
    shikimori_id: str | None = None
    method: Literal["title_year_kind", "same_source"] | None = None


class CatalogPage(BaseModel):
    details: AnimeDetails
    related: list[RelatedAnime] = Field(default_factory=list)
    playback: PlaybackMatch
    warnings: list[str] = Field(default_factory=list)


class CatalogCollectionInfo(BaseModel):
    slug: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=100)
    order: Literal["ranked", "popularity"]


class CatalogCollection(CatalogCollectionInfo):
    items: list[AnimeCard] = Field(default_factory=list)


class HomeCatalog(BaseModel):
    ongoing: list[AnimeCard] = Field(default_factory=list)
    popular: list[AnimeCard] = Field(default_factory=list)
    collections: list[CatalogCollectionInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Episode(BaseModel):
    number: int = Field(ge=1)
    title: str | None = None
    air_date: str | None = None
    is_released: bool | None = None


class EpisodeList(BaseModel):
    source: AnimeSource
    external_id: str
    episodes: list[Episode]


class VoiceEpisodeCatalog(BaseModel):
    episodes: list[int]
    status: Literal["ready", "unsupported"] = "ready"
    message: str | None = None
    checked: int = Field(ge=0)
    total: int = Field(ge=0)
    next_offset: None = None


class Translation(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    player: str | None = None
    kind: str | None = None
    embed_url: AnyHttpUrl | None = None
    episodes_start: int | None = Field(None, ge=0)
    episodes_end: int | None = Field(None, ge=0)
    source: Literal["animego", "kodik"] = "animego"


class PlayerInfo(BaseModel):
    source: AnimeSource
    external_id: str
    id_source: AnimeSource
    episodes_total: int | None = Field(None, ge=0)
    translations: list[Translation]
    episodes: list[int] = Field(default_factory=list)


class StreamVariant(BaseModel):
    url: AnyHttpUrl
    format: Literal["hls", "dash", "mp4"]
    quality: StreamQuality | None = None


class StreamInfo(BaseModel):
    source: AnimeSource
    external_id: str
    id_source: AnimeSource
    episode: int = Field(ge=0)
    translation_id: str
    translation_name: str | None = None
    player: str
    streams: list[StreamVariant] = Field(min_length=1)
