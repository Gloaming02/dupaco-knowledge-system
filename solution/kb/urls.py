"""URL normalisation: one identity per page, however the crawler spelled it."""
from urllib.parse import urlparse


def url_key(url: str) -> str:
    """'https://www.dupaco.com/Rates/?hsLang=en#x' -> 'dupaco.com/rates'."""
    p = urlparse(url if "//" in url else "https://" + url)
    host = p.netloc.lower().removeprefix("www.")
    return host + (p.path.rstrip("/").lower() or "")


def path_of(url: str) -> str:
    return urlparse(url if "//" in url else "https://" + url).path.rstrip("/").lower() or "/"
