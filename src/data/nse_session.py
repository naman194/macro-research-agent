"""Authenticated NSE session — handles cookie warmup needed for protected endpoints.

NSE's public API (nseindia.com/api/*) sits behind an Akamai bot filter that requires:
  1. A real browser User-Agent
  2. A cookie set obtained by first visiting nseindia.com homepage
  3. Referer header on subsequent calls

This helper builds & refreshes that session, and provides a `.get_json(url, params)`
helper that auto-refreshes cookies on 401/403.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)


_HOMEPAGE = "https://www.nseindia.com/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    # Drop brotli — requests can't decode `br` without brotli pip dep, and NSE
    # otherwise sends compressed responses that fail json parsing.
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

# Process-wide singleton — NSE rate-limits per IP so we share one session.
_lock = threading.Lock()
_session: Optional[requests.Session] = None
_session_warmed_at: float = 0.0
_SESSION_TTL = 30 * 60  # 30 min


def _warm() -> requests.Session:
    global _session, _session_warmed_at
    s = requests.Session()
    s.headers.update(_HEADERS)
    try:
        # First hit homepage to seed cookies, then a "warm" API call so JS cookies are set
        s.get(_HOMEPAGE, timeout=15)
        s.get("https://www.nseindia.com/option-chain", timeout=15)
    except Exception as exc:
        log.warning("NSE cookie warmup failed: %s", exc)
    _session = s
    _session_warmed_at = time.time()
    return s


def session(force_refresh: bool = False) -> requests.Session:
    """Return a warmed NSE session, refreshing if stale."""
    global _session, _session_warmed_at
    with _lock:
        if force_refresh or _session is None or (time.time() - _session_warmed_at) > _SESSION_TTL:
            return _warm()
        return _session


def get_json(path_or_url: str, params: Optional[Dict[str, Any]] = None,
             retries: int = 2, timeout: int = 20) -> Optional[Any]:
    """Fetch a JSON endpoint behind NSE WAF. Returns parsed JSON or None on failure."""
    url = path_or_url if path_or_url.startswith("http") else f"https://www.nseindia.com{path_or_url}"
    for attempt in range(retries + 1):
        s = session(force_refresh=(attempt > 0))
        try:
            r = s.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    log.warning("NSE %s returned non-JSON: %s", url, r.text[:200])
                    return None
            if r.status_code in (401, 403, 429):
                log.info("NSE %s -> %s, will retry with fresh session", url, r.status_code)
                continue
            log.warning("NSE %s -> %s", url, r.status_code)
            return None
        except Exception as exc:
            log.warning("NSE %s err: %s", url, exc)
            time.sleep(1)
    return None
