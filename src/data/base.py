"""Base class for data adapters + shared HTTP session with retries."""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data import cache

log = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def make_session(extra_headers: Optional[dict] = None) -> requests.Session:
    s = requests.Session()
    s.headers.update(_DEFAULT_HEADERS)
    if extra_headers:
        s.headers.update(extra_headers)
    return s


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
def fetch_json(session: requests.Session, url: str, **kw) -> Any:
    r = session.get(url, timeout=30, **kw)
    r.raise_for_status()
    return r.json()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
def fetch_text(session: requests.Session, url: str, **kw) -> str:
    r = session.get(url, timeout=30, **kw)
    r.raise_for_status()
    return r.text


class DataAdapter:
    """Adapter base. Subclasses implement source-specific calls.

    All public methods should go through `_cached` so we don't hammer upstream.
    """

    namespace: str = "base"
    default_ttl: int = 3600

    def __init__(self) -> None:
        self.session = make_session()

    def _cached(
        self,
        parts: tuple,
        loader: Callable[[], Any],
        ttl: Optional[int] = None,
    ) -> Any:
        hit = cache.get(self.namespace, *parts)
        if hit is not None:
            return hit
        try:
            value = loader()
        except Exception as exc:
            log.warning("adapter %s loader failed for %s: %s", self.namespace, parts, exc)
            raise
        cache.set_(self.namespace, parts, value, ttl or self.default_ttl)
        return value
