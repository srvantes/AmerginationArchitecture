"""Public anime addresses; provider identities stay unchanged inside the API."""
import re
import unicodedata


_LETTERS = str.maketrans(dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "yo", "zh", "z", "i", "y", "k", "l", "m", "n", "o",
     "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"],
)))
_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_PUBLIC = re.compile(r"([a-z0-9]+(?:-[a-z0-9]+)*)-(a?)([1-9][0-9]{0,19})\Z")


def title_slug(title):
    value = unicodedata.normalize("NFKD", str(title or "").lower().translate(_LETTERS))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")[:160].rstrip("-") or "anime"


def anime_path(source, external_id, title="", original_title=None, slug=None, *, public_slug=None):
    external_id = str(external_id)
    if source not in {"shikimori", "animego"} or not _ID.fullmatch(external_id):
        return None
    # AnimeGo still needs its exact upstream slug to load a cold detail page.
    name = slug if source == "animego" and isinstance(slug, str) and len(slug) <= 300 and _SLUG.fullmatch(slug) else title_slug(original_title or title)
    if isinstance(public_slug, str) and len(public_slug) <= 300 and _SLUG.fullmatch(public_slug):
        name = public_slug
    # The compact 'a' namespace prevents two providers' numeric IDs colliding.
    marker = "a" if source == "animego" else ""
    return f"/anime/{name}-{marker}{external_id}"


def parse_anime_key(value):
    if not isinstance(value, str) or len(value) > 323:
        return None
    match = _PUBLIC.fullmatch(value)
    if not match:
        return None
    slug, marker, external_id = match.groups()
    return {"source": "animego" if marker else "shikimori", "external_id": external_id, "slug": slug}
