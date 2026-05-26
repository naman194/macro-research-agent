"""Bulk concall ingestion — best-effort auto-fetch + analyze loop.

For each ticker, discover transcript URLs via concall_archive.list_documents(),
attempt to download each PDF, extract text, and run analyze_and_persist().

What can go wrong (gracefully):
  - PDF behind Cloudflare → request returns 403 / 5xx → logged, skipped
  - PDF is gated (login required) → returns HTML page → text extract empty → skipped
  - PDF has no quarter label in filename → we attempt to parse from text
  - Claude rate limit / unavailable → analyze_and_persist returns parse_ok=False → recorded
  - Same (ticker, quarter) already in archive → skipped (idempotent)

Output is structured so the UI can show a per-ticker / per-call status table.
"""
from __future__ import annotations

import io
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

from src.agent.concall import ConcallAgent, ConcallInput, extract_pdf_text
from src.data.concall_archive import (
    ConcallArchive,
    TranscriptLink,
    list_documents,
)

log = logging.getLogger(__name__)


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
REQ_TIMEOUT = 30
PDF_MAGIC = b"%PDF-"


@dataclass
class IngestResult:
    ticker: str
    quarter: Optional[str]
    url: str
    label: str
    status: str        # "ok" | "skipped_already" | "fetch_failed" | "not_pdf" | "extract_empty" | "analyze_failed"
    detail: str = ""


@dataclass
class IngestSummary:
    ticker: str
    attempted: int = 0
    ingested: int = 0
    skipped_already: int = 0
    failed: int = 0
    results: List[IngestResult] = field(default_factory=list)


def _download_pdf(url: str) -> Optional[bytes]:
    """Fetch the URL. Returns bytes if response looks like a PDF, else None."""
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/pdf,*/*"},
                         timeout=REQ_TIMEOUT, allow_redirects=True)
    except Exception as exc:
        log.info("download_pdf %s: %s", url, exc)
        return None
    if r.status_code != 200:
        log.info("download_pdf %s: HTTP %d", url, r.status_code)
        return None
    if not r.content.startswith(PDF_MAGIC):
        return None
    return r.content


# Best-effort quarter parse from transcript text when the filename doesn't contain it.
_TEXT_QRX = re.compile(r"\bQ([1-4])\s*FY\s*(\d{2,4})\b", re.IGNORECASE)
_TEXT_QRX_ALT = re.compile(r"\bquarter ended\s*\w*\s*(\d{1,2})\s*[, ]\s*(\d{4})\b",
                           re.IGNORECASE)
_MONTH_TO_QUARTER = {
    # Indian FY: Apr-Jun=Q1, Jul-Sep=Q2, Oct-Dec=Q3, Jan-Mar=Q4
    1: "Q4", 2: "Q4", 3: "Q4",
    4: "Q1", 5: "Q1", 6: "Q1",
    7: "Q2", 8: "Q2", 9: "Q2",
    10: "Q3", 11: "Q3", 12: "Q3",
}


def _quarter_from_transcript(text: str) -> Optional[str]:
    """Try to parse Q-FY from first 2000 chars of transcript. The opening
    welcome line usually states it explicitly."""
    head = text[:2500]
    m = _TEXT_QRX.search(head)
    if m:
        q, fy = m.group(1), m.group(2)
        if len(fy) == 4:
            fy = fy[-2:]
        return f"Q{q} FY{fy}"
    return None


def ingest_ticker(ticker: str,
                  max_calls: int = 4,
                  archive: Optional[ConcallArchive] = None,
                  agent: Optional[ConcallAgent] = None,
                  company_name: Optional[str] = None) -> IngestSummary:
    """Discover transcript URLs for `ticker`, ingest up to max_calls in newest-first order.

    Idempotent — if a (ticker, quarter) already exists in the archive, we skip without
    re-running Claude.
    """
    archive = archive or ConcallArchive()
    agent = agent or ConcallAgent()
    existing_quarters = {r.quarter for r in archive.list_for_ticker(ticker, limit=50)}

    summary = IngestSummary(ticker=ticker)

    try:
        docs = list_documents(ticker)
    except Exception as exc:
        log.warning("list_documents %s: %s", ticker, exc)
        return summary

    transcripts: List[TranscriptLink] = [d for d in docs if d.inferred_kind == "transcript"]
    if not transcripts:
        return summary

    for d in transcripts[:max_calls]:
        summary.attempted += 1
        quarter_hint = d.inferred_quarter

        # Idempotency check via inferred quarter
        if quarter_hint and quarter_hint in existing_quarters:
            summary.skipped_already += 1
            summary.results.append(IngestResult(
                ticker=ticker, quarter=quarter_hint, url=d.url, label=d.label,
                status="skipped_already", detail="already in archive",
            ))
            continue

        # Fetch
        pdf = _download_pdf(d.url)
        if pdf is None:
            summary.failed += 1
            summary.results.append(IngestResult(
                ticker=ticker, quarter=quarter_hint, url=d.url, label=d.label,
                status="fetch_failed", detail="HTTP non-200 or non-PDF response",
            ))
            continue

        # Extract text
        text = extract_pdf_text(pdf)
        if not text or len(text) < 1000:
            summary.failed += 1
            summary.results.append(IngestResult(
                ticker=ticker, quarter=quarter_hint, url=d.url, label=d.label,
                status="extract_empty", detail=f"text len {len(text)}",
            ))
            continue

        # Parse quarter from text if not in label
        quarter = quarter_hint or _quarter_from_transcript(text)
        if not quarter:
            summary.failed += 1
            summary.results.append(IngestResult(
                ticker=ticker, quarter=None, url=d.url, label=d.label,
                status="extract_empty", detail="could not parse quarter from text or label",
            ))
            continue
        if quarter in existing_quarters:
            summary.skipped_already += 1
            summary.results.append(IngestResult(
                ticker=ticker, quarter=quarter, url=d.url, label=d.label,
                status="skipped_already", detail="already in archive (post-parse)",
            ))
            continue

        # Analyze + persist
        payload = ConcallInput(
            ticker=ticker, company_name=company_name or ticker,
            quarter=quarter, transcript_text=text,
        )
        try:
            res = agent.analyze_and_persist(payload)
            if res.parse_ok:
                summary.ingested += 1
                existing_quarters.add(quarter)
                summary.results.append(IngestResult(
                    ticker=ticker, quarter=quarter, url=d.url, label=d.label,
                    status="ok", detail=f"tone={res.tone} · guidance={len(res.guidance)}",
                ))
            else:
                summary.failed += 1
                summary.results.append(IngestResult(
                    ticker=ticker, quarter=quarter, url=d.url, label=d.label,
                    status="analyze_failed", detail=res.parse_error or "parse failed",
                ))
        except Exception as exc:
            summary.failed += 1
            summary.results.append(IngestResult(
                ticker=ticker, quarter=quarter, url=d.url, label=d.label,
                status="analyze_failed", detail=str(exc),
            ))
        # Be polite to upstream
        time.sleep(0.5)

    return summary


def bulk_ingest(tickers: List[str], max_calls_per_ticker: int = 2,
                throttle_seconds: float = 1.0) -> List[IngestSummary]:
    """Run ingest_ticker across multiple tickers. Returns one summary per ticker."""
    archive = ConcallArchive()
    agent = ConcallAgent()
    summaries: List[IngestSummary] = []
    for t in tickers:
        s = ingest_ticker(t, max_calls=max_calls_per_ticker,
                          archive=archive, agent=agent)
        summaries.append(s)
        time.sleep(throttle_seconds)
    return summaries
