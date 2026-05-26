"""Concall archive — SQLite-backed history of analyzed concalls per ticker.

Stores structured extraction (tone, guidance, concerns, positives) for every
transcript that has been analyzed. The point isn't to store transcripts (large)
but to store the *signals* (small, comparable across quarters) so we can answer:
  - Did this management hit the guidance they gave last quarter?
  - How has tone drifted?
  - Are the same concerns appearing every quarter? (= unresolved = lower credibility)

Two-part design:
  1. SQLite store (`concall_history` table) — the source of truth
  2. URL discovery helper for screener.in's Documents tab — lists transcripts
     available for download. Full auto-download deferred to Phase B (some PDFs
     are behind Cloudflare / require auth).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from src.config import SCREENER_PREMIUM_SESSIONID, SCREENER_SLUG_OVERRIDES
from src.data.base import fetch_text

log = logging.getLogger(__name__)


# =========================================================================
# SQLite layer
# =========================================================================

CONCALL_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data_cache", "concall_history.db",
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS concall_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    company_name TEXT,
    quarter TEXT NOT NULL,
    call_date TEXT,
    fetched_at TEXT NOT NULL,
    tone TEXT,
    net_assessment TEXT,
    guidance_json TEXT,
    concerns_json TEXT,
    positives_json TEXT,
    pressure_points_json TEXT,
    verbatim_quotes_json TEXT,
    markdown_analysis TEXT,
    transcript_chars INTEGER,
    UNIQUE(ticker, quarter)
);

CREATE INDEX IF NOT EXISTS idx_concall_ticker
    ON concall_history(ticker, call_date DESC);
"""


@dataclass
class ConcallRecord:
    """One stored concall analysis. Lists/dicts serialise to JSON in SQLite."""
    ticker: str
    company_name: Optional[str]
    quarter: str                              # "Q4 FY26"
    call_date: Optional[str] = None           # ISO YYYY-MM-DD
    tone: Optional[str] = None
    net_assessment: Optional[str] = None
    guidance: List[Dict[str, Any]] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    positives: List[str] = field(default_factory=list)
    pressure_points: List[Dict[str, Any]] = field(default_factory=list)
    verbatim_quotes: List[Dict[str, Any]] = field(default_factory=list)
    markdown_analysis: Optional[str] = None
    transcript_chars: Optional[int] = None
    fetched_at: Optional[str] = None


@contextmanager
def _connect():
    os.makedirs(os.path.dirname(CONCALL_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(CONCALL_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Execute schema as a script (multiple statements separated by ;)
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


class ConcallArchive:
    """SQLite-backed store of structured concall extractions."""

    def save(self, rec: ConcallRecord) -> int:
        """Upsert a record. Returns row id. Existing (ticker, quarter) is replaced."""
        rec.fetched_at = rec.fetched_at or datetime.utcnow().isoformat(timespec="seconds")
        with _connect() as conn:
            cur = conn.execute(
                """INSERT INTO concall_history
                   (ticker, company_name, quarter, call_date, fetched_at,
                    tone, net_assessment, guidance_json, concerns_json,
                    positives_json, pressure_points_json, verbatim_quotes_json,
                    markdown_analysis, transcript_chars)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(ticker, quarter) DO UPDATE SET
                     company_name=excluded.company_name,
                     call_date=excluded.call_date,
                     fetched_at=excluded.fetched_at,
                     tone=excluded.tone,
                     net_assessment=excluded.net_assessment,
                     guidance_json=excluded.guidance_json,
                     concerns_json=excluded.concerns_json,
                     positives_json=excluded.positives_json,
                     pressure_points_json=excluded.pressure_points_json,
                     verbatim_quotes_json=excluded.verbatim_quotes_json,
                     markdown_analysis=excluded.markdown_analysis,
                     transcript_chars=excluded.transcript_chars
                """,
                (rec.ticker.upper(), rec.company_name, rec.quarter, rec.call_date,
                 rec.fetched_at, rec.tone, rec.net_assessment,
                 json.dumps(rec.guidance, default=str),
                 json.dumps(rec.concerns, default=str),
                 json.dumps(rec.positives, default=str),
                 json.dumps(rec.pressure_points, default=str),
                 json.dumps(rec.verbatim_quotes, default=str),
                 rec.markdown_analysis, rec.transcript_chars)
            )
            return cur.lastrowid

    def list_for_ticker(self, ticker: str, limit: int = 20) -> List[ConcallRecord]:
        """Return all stored calls for a ticker, newest first."""
        with _connect() as conn:
            rows = conn.execute(
                """SELECT * FROM concall_history WHERE ticker = ?
                   ORDER BY call_date DESC, quarter DESC LIMIT ?""",
                (ticker.upper(), limit)
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def latest(self, ticker: str) -> Optional[ConcallRecord]:
        recs = self.list_for_ticker(ticker, limit=1)
        return recs[0] if recs else None

    def prior(self, ticker: str, before_quarter: str) -> Optional[ConcallRecord]:
        """The most recent call BEFORE the given quarter (for delta analysis)."""
        recs = self.list_for_ticker(ticker, limit=20)
        for r in recs:
            if r.quarter != before_quarter:
                return r
        return None

    def all_tickers(self) -> List[str]:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM concall_history ORDER BY ticker"
            ).fetchall()
        return [r["ticker"] for r in rows]

    def stats(self) -> Dict[str, int]:
        with _connect() as conn:
            n_rows = conn.execute("SELECT COUNT(*) AS c FROM concall_history").fetchone()["c"]
            n_tick = conn.execute("SELECT COUNT(DISTINCT ticker) AS c FROM concall_history").fetchone()["c"]
        return {"rows": int(n_rows), "tickers": int(n_tick)}

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ConcallRecord:
        def _decode(s):
            try: return json.loads(s) if s else []
            except Exception: return []
        return ConcallRecord(
            ticker=row["ticker"],
            company_name=row["company_name"],
            quarter=row["quarter"],
            call_date=row["call_date"],
            fetched_at=row["fetched_at"],
            tone=row["tone"],
            net_assessment=row["net_assessment"],
            guidance=_decode(row["guidance_json"]),
            concerns=_decode(row["concerns_json"]),
            positives=_decode(row["positives_json"]),
            pressure_points=_decode(row["pressure_points_json"]),
            verbatim_quotes=_decode(row["verbatim_quotes_json"]),
            markdown_analysis=row["markdown_analysis"],
            transcript_chars=row["transcript_chars"],
        )


# =========================================================================
# URL discovery — screener.in Documents tab
# Returns a list of transcript URLs the user can manually download.
# Full auto-fetch is Phase B (Cloudflare + occasional auth-gated PDFs).
# =========================================================================

SCREENER_BASE = "https://www.screener.in"


@dataclass
class TranscriptLink:
    label: str            # "Q4FY24 Concall Transcript" or similar
    url: str
    inferred_quarter: Optional[str] = None    # parsed from label, e.g. "Q4 FY24"
    inferred_kind: Optional[str] = None       # "transcript" | "presentation" | "press release" | "other"


_QUARTER_RX = re.compile(
    r"(Q[1-4])[\s\-]*FY[\s\-]*(\d{2,4})", re.IGNORECASE
)


def _infer_quarter(label: str) -> Optional[str]:
    m = _QUARTER_RX.search(label or "")
    if not m:
        return None
    q, fy = m.group(1).upper(), m.group(2)
    # Normalise FY24 -> 24, FY2024 -> 24
    if len(fy) == 4:
        fy = fy[-2:]
    return f"{q} FY{fy}"


def _infer_kind(label: str) -> Optional[str]:
    s = (label or "").lower()
    if "transcript" in s: return "transcript"
    if "concall" in s or "earnings call" in s: return "transcript"
    if "presentation" in s or "investor ppt" in s: return "presentation"
    if "press release" in s or "press note" in s: return "press_release"
    if "result" in s or "financial" in s: return "results"
    return "other"


def list_documents(ticker: str) -> List[TranscriptLink]:
    """Scrape screener.in's Documents section for a ticker. Returns concall
    transcripts + investor presentations (the most useful pair for analysis).

    Read-only — does not download. User clicks the URL to fetch the PDF, then
    uploads it back through the UI for analysis.
    """
    slug = SCREENER_SLUG_OVERRIDES.get(ticker.upper(), ticker.upper())
    sess = requests.Session()
    if SCREENER_PREMIUM_SESSIONID:
        sess.cookies.set("sessionid", SCREENER_PREMIUM_SESSIONID, domain="screener.in")

    out: List[TranscriptLink] = []
    for path in (f"/company/{slug}/consolidated/", f"/company/{slug}/"):
        try:
            html = fetch_text(sess, SCREENER_BASE + path)
        except Exception:
            continue
        soup = BeautifulSoup(html, "lxml")
        # Documents section is a div/section with anchors to .pdf or external IR pages.
        # Heuristic: anchors whose href contains ".pdf" OR text contains "Transcript"/"Concall".
        for a in soup.find_all("a"):
            href = a.get("href", "") or ""
            label = a.get_text(" ", strip=True)
            if not label:
                continue
            href_l = href.lower()
            label_l = label.lower()
            is_pdf = href_l.endswith(".pdf") or ".pdf?" in href_l
            looks_like_concall = any(k in label_l for k in
                                     ["transcript", "concall", "earnings call",
                                      "investor presentation", "investor ppt"])
            if not (is_pdf and looks_like_concall):
                continue
            if href.startswith("/"):
                full_url = SCREENER_BASE + href
            elif href.startswith("http"):
                full_url = href
            else:
                continue
            out.append(TranscriptLink(
                label=label, url=full_url,
                inferred_quarter=_infer_quarter(label),
                inferred_kind=_infer_kind(label),
            ))
        if out:
            break  # use the first path that yielded results

    # Dedup by URL preserving order
    seen = set()
    deduped = []
    for t in out:
        if t.url in seen: continue
        seen.add(t.url)
        deduped.append(t)
    # Prefer transcripts at top
    deduped.sort(key=lambda t: (0 if t.inferred_kind == "transcript" else 1,))
    return deduped
