"""SQLite-backed key-value cache with per-entry TTL.

Used by all data adapters to avoid hammering upstream APIs.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Optional

from src.config import CACHE_DB


def _key(namespace: str, parts: tuple) -> str:
    payload = json.dumps([namespace, list(parts)], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


@contextmanager
def _conn():
    con = sqlite3.connect(CACHE_DB, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_cache() -> None:
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                value TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS ix_cache_ns ON cache(namespace)")
        con.execute("CREATE INDEX IF NOT EXISTS ix_cache_exp ON cache(expires_at)")


def get(namespace: str, *parts: Any) -> Optional[Any]:
    init_cache()
    k = _key(namespace, parts)
    with _conn() as con:
        row = con.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (k,)
        ).fetchone()
    if not row:
        return None
    if row["expires_at"] < time.time():
        return None
    return json.loads(row["value"])


def set_(namespace: str, parts: tuple, value: Any, ttl_seconds: int) -> None:
    init_cache()
    k = _key(namespace, parts)
    now = time.time()
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO cache (key, namespace, value, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (k, namespace, json.dumps(value, default=str), now + ttl_seconds, now),
        )


def purge_expired() -> int:
    init_cache()
    with _conn() as con:
        cur = con.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
        return cur.rowcount


def clear_namespace(namespace: str) -> int:
    init_cache()
    with _conn() as con:
        cur = con.execute("DELETE FROM cache WHERE namespace = ?", (namespace,))
        return cur.rowcount
