"""Normalize poster links and exclude upstream 'missing image' artwork."""
from urllib.parse import urljoin, urlsplit


def poster_url(value, base=None):
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.startswith("//"):
        value = "https:" + value
    elif base:
        value = urljoin(base, value)
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or any(ord(char) < 32 for char in value)):
            return None
        parsed.port
    except ValueError:
        return None
    if (parsed.hostname in {"shikimori.io", "shikimori.one", "www.shikimori.io", "www.shikimori.one"}
            and parsed.path.lower().startswith("/assets/globals/missing")):
        return None
    return value
