"""Brief history store — per-day record of every pick the morning brief surfaces.

Purpose: answer "is this name NEW today, or has it been on the brief for N days?"
That delta is one of the highest-signal pieces for buyside readers — a name that
just entered the screen is fresh; a name persisting 5 days suggests durable
fundamentals (or a stale screen the operator hasn't acted on).

Schema is intentionally simple — one row per (date, ticker, section). The
raw_json column captures the full pick dict so future schema changes don't
require backfilling.

Storage: /app/data_cache/brief_history.db (Railway persistent volume) so
day-over-day state survives redeploys.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from src.config import CACHE_DIR

log = logging.getLogger(__name__)

DB_PATH = CACHE_DIR / "brief_history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS brief_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_date TEXT NOT NULL,        -- ISO YYYY-MM-DD
    ticker TEXT NOT NULL,
    section TEXT NOT NULL,           -- 'qv' | 'garp' | 'high_conviction' | 'special' | 'focus'
    score REAL,
    rank_in_section INTEGER,
    raw_json TEXT,
    saved_at TEXT NOT NULL,
    UNIQUE(brief_date, ticker, section)
);

CREATE INDEX IF NOT EXISTS idx_brief_date ON brief_history(brief_date DESC);
CREATE INDEX IF NOT EXISTS idx_brief_ticker_date ON brief_history(ticker, brief_date DESC);
"""


@dataclass
class TickerDelta:
    ticker: str
    days_in_brief: int       # consecutive days back from today (1 = today only = new)
    first_seen: Optional[str]
    last_seen: Optional[str]
    sections_today: List[str]
    is_new: bool             # True if this ticker did NOT appear in the most recent prior brief


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


class BriefHistoryStore:
    """SQLite-backed daily-brief picks recorder."""

    def save_brief(self, brief_date: str,
                   picks_by_section: Dict[str, List[Dict[str, Any]]]) -> int:
        """Persist all picks for one brief date. Idempotent — replaces same
        (date, ticker, section) rows. Returns number of rows written."""
        if not brief_date:
            brief_date = date.today().isoformat()
        now = datetime.utcnow().isoformat(timespec="seconds")
        rows = 0
        with _connect() as conn:
            for section, picks in (picks_by_section or {}).items():
                for rank, pick in enumerate(picks or [], start=1):
                    ticker = (pick.get("ticker") or pick.get("symbol") or "").upper()
                    if not ticker:
                        continue
                    score = pick.get("score") or pick.get("conviction_score")
                    try:
                        score = float(score) if score is not None else None
                    except (TypeError, ValueError):
                        score = None
                    conn.execute(
                        """INSERT INTO brief_history
                           (brief_date, ticker, section, score, rank_in_section,
                            raw_json, saved_at)
                           VALUES (?,?,?,?,?,?,?)
                           ON CONFLICT(brief_date, ticker, section) DO UPDATE SET
                             score=excluded.score,
                             rank_in_section=excluded.rank_in_section,
                             raw_json=excluded.raw_json,
                             saved_at=excluded.saved_at""",
                        (brief_date, ticker, section, score, rank,
                         json.dumps(pick, default=str), now)
                    )
                    rows += 1
        return rows

    def picks_for_date(self, brief_date: str) -> Dict[str, List[str]]:
        """Tickers surfaced on a given brief date, grouped by section."""
        out: Dict[str, List[str]] = {}
        with _connect() as conn:
            for row in conn.execute(
                "SELECT section, ticker FROM brief_history WHERE brief_date = ? "
                "ORDER BY section, rank_in_section",
                (brief_date,)
            ):
                out.setdefault(row["section"], []).append(row["ticker"])
        return out

    def latest_brief_date(self, before: Optional[str] = None) -> Optional[str]:
        """Most recent brief_date in the store, optionally before a cutoff."""
        with _connect() as conn:
            if before:
                row = conn.execute(
                    "SELECT MAX(brief_date) AS d FROM brief_history WHERE brief_date < ?",
                    (before,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT MAX(brief_date) AS d FROM brief_history"
                ).fetchone()
        return row["d"] if row and row["d"] else None

    def delta_for_ticker(self, ticker: str, today: str,
                         lookback_days: int = 14) -> TickerDelta:
        """How many consecutive prior briefs did this ticker appear in?"""
        ticker = ticker.upper()
        with _connect() as conn:
            rows = conn.execute(
                """SELECT brief_date, GROUP_CONCAT(section) AS sections
                   FROM brief_history
                   WHERE ticker = ? AND brief_date <= ?
                   GROUP BY brief_date
                   ORDER BY brief_date DESC
                   LIMIT ?""",
                (ticker, today, lookback_days + 1)
            ).fetchall()

        if not rows:
            return TickerDelta(ticker=ticker, days_in_brief=0, first_seen=None,
                                last_seen=None, sections_today=[], is_new=True)

        # The first row is today (or the latest prior brief if not yet saved).
        # Walk backwards counting consecutive days. We accept gaps of weekends —
        # if there's no brief for >2 calendar days, treat the streak as broken.
        from datetime import timedelta
        sections_today: List[str] = []
        if rows[0]["brief_date"] == today:
            sections_today = (rows[0]["sections"] or "").split(",")
            sections_today = [s for s in sections_today if s]
            streak_start_idx = 0
        else:
            streak_start_idx = -1   # ticker not in today's brief at all (shouldn't happen here)

        days_in_brief = 0
        prev_date = None
        for r in rows:
            d = datetime.fromisoformat(r["brief_date"]).date()
            if prev_date is None:
                days_in_brief = 1
            else:
                gap = (prev_date - d).days
                if gap <= 3:  # tolerate weekends / one missed day
                    days_in_brief += 1
                else:
                    break
            prev_date = d

        first_seen = rows[-1]["brief_date"] if rows else None
        last_seen = rows[0]["brief_date"] if rows else None

        # is_new = appeared today but not in the prior brief
        prior_date = self.latest_brief_date(before=today)
        is_new = True
        if prior_date:
            prior_picks_any = any(r["brief_date"] == prior_date for r in rows)
            is_new = not prior_picks_any

        return TickerDelta(
            ticker=ticker,
            days_in_brief=days_in_brief,
            first_seen=first_seen,
            last_seen=last_seen,
            sections_today=sections_today,
            is_new=is_new,
        )

    def stats(self) -> Dict[str, int]:
        with _connect() as conn:
            n_rows = conn.execute("SELECT COUNT(*) AS c FROM brief_history").fetchone()["c"]
            n_dates = conn.execute(
                "SELECT COUNT(DISTINCT brief_date) AS c FROM brief_history"
            ).fetchone()["c"]
            n_tickers = conn.execute(
                "SELECT COUNT(DISTINCT ticker) AS c FROM brief_history"
            ).fetchone()["c"]
        return {"rows": int(n_rows), "dates": int(n_dates), "tickers": int(n_tickers)}
