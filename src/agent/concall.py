"""Concall transcript analyzer.

Pipeline:
  1. User uploads concall transcript PDF (or pastes text)
  2. pypdf extracts text
  3. Claude reads transcript + structured prompt → outputs:
     (a) Markdown analyst note (human-readable)
     (b) JSON structured extraction (machine-readable: tone, guidance items,
         concerns, positives, pressure points, verbatim quotes)
  4. Structured extraction is persisted to concall_history.db, keyed
     by (ticker, quarter), feeding the "Track Record" view.

Best transcripts sourced from:
  - screener.in: https://www.screener.in/company/{TICKER}/consolidated/ → "Documents" tab
  - AlphaStreet: https://research.alphastreet.com/
  - Company IR pages
  - BSE/NSE corporate filings
"""
from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

log = logging.getLogger(__name__)


CONCALL_SYSTEM = """You are a senior buyside analyst at an Indian institutional fund. \
You read every concall transcript on names you cover. Your job: turn a 40-80 page \
transcript into a 1-page institutional analyst's read that captures what actually changed \
and what the desk needs to know.

OUTPUT FORMAT (Markdown, exact structure):

# {COMPANY} Concall — {QUARTER} Analyst Read

**Management tone:** Bullish / Confident / Cautious / Defensive / Hesitant. One-line justification.

**Net call assessment:** Net Positive / Net Neutral / Net Negative.

## What changed
3-5 bullets on the *deltas* vs prior call / Street view. Be concrete:
- Guidance reset (specific numbers, direction)
- New disclosures (margin trajectory, capex plan, segment splits)
- Strategic pivots (M&A signals, capacity additions, restructuring)
- Things they *stopped* talking about (often the biggest tell)

## Key positives
3-4 bullets with the specific data point or quote.

## Key concerns / red flags
3-4 bullets. Be honest — these are the things that should make us re-rate the downside case.

## Notable Q&A — analyst pressure points
Identify 2-3 places where analysts pushed and management deflected, hedged, or had \
to clarify. Quote the exact exchange if possible. This is where the real signal is.

## Verbatim quotes worth flagging
Pull 3-5 short verbatim quotes that capture the message. Format:
> "Quote here" — Speaker (CEO / CFO / EVP etc.)

## Read for the model
2-3 bullets describing what this transcript implies for the structural picture. Does \
management commentary support or weaken what our screen identifies? Are consensus estimates \
likely to move based on guidance? Is the historical valuation band still a reasonable anchor \
or is there evidence of structural re-rating? Use observational language ("transcript suggests", \
"guidance implies", "data points to"), not prescriptive ("buy", "sell", "we recommend").

## Disclaimer
Reproduce verbatim: "**This analysis is informational, NOT investment advice or a \
recommendation to buy, sell or hold any security. The author is not a SEBI-registered Research \
Analyst or Investment Adviser. Verify all quotes and figures against the official company \
transcript before any action.**"

---

AFTER the markdown analysis above, output one final block — a structured \
JSON snapshot of the call, wrapped in `<structured>` XML tags. This is \
persisted to a database and compared across quarters to build a management \
credibility track-record. The JSON MUST conform to this schema:

<structured>
{
  "tone": "bullish | confident | cautious | defensive | hesitant | neutral",
  "net_assessment": "net_positive | net_neutral | net_negative",
  "call_date": "YYYY-MM-DD or null if not stated in transcript",
  "guidance": [
    {
      "metric": "revenue_growth | ebitda_margin | net_profit | capex | volume_growth | \
new_orders | gross_margin | other (be specific in label)",
      "label": "human label e.g. 'FY27 revenue growth band'",
      "value": "e.g. '8-10%' or 'Rs 4,500 Cr' or '18-19%'",
      "period": "e.g. 'FY27' or 'Q1FY27' or 'medium-term'",
      "direction": "new | reiterated | raised | lowered | withdrawn",
      "confidence": "high | medium | low (your read of how committed management seemed)"
    }
  ],
  "concerns": ["short concern strings, 3-6 items"],
  "positives": ["short positive strings, 3-6 items"],
  "pressure_points": [
    {"topic": "e.g. 'margin trajectory'", "exchange": "1-sentence summary of the push-back \
or hedge"}
  ],
  "verbatim_quotes": [
    {"speaker": "CEO / CFO / COO / EVP — Segment X", "quote": "exact text from transcript"}
  ]
}
</structured>

CRITICAL: every guidance item must include `value` and `period`. If management \
withdrew prior guidance, record `direction: withdrawn` with `value: null`. If a \
quarter's call gave NO numeric guidance, return `guidance: []` (do not invent).

HARD RULES:
- **No fabrication.** Only use what's in the transcript text.
- **Use the speaker's exact words** for the verbatim quote section — institutional \
clients verify these.
- If transcript is incomplete or cut off, say so at the top.
- Keep markdown analysis under 700 words. The JSON block is in addition, not counted.
- Match Indian institutional voice: "FY26E", "Q4FY26", "guidance revised down 100bps", \
"capex spend Rs 4,500 Cr", "EBITDA margin band".
- The `<structured>` block must be valid JSON. Validate it before returning.
"""


@dataclass
class ConcallInput:
    ticker: str
    company_name: str
    quarter: str          # e.g. "Q4 FY26"
    transcript_text: str  # raw text from PDF extract or paste
    prior_call_summary: Optional[str] = None  # optional — for delta analysis


@dataclass
class ConcallAnalysis:
    """Both faces of a concall analysis: markdown for humans, JSON for the
    longitudinal store."""
    markdown: str
    tone: Optional[str] = None
    net_assessment: Optional[str] = None
    call_date: Optional[str] = None
    guidance: List[Dict[str, Any]] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    positives: List[str] = field(default_factory=list)
    pressure_points: List[Dict[str, Any]] = field(default_factory=list)
    verbatim_quotes: List[Dict[str, Any]] = field(default_factory=list)
    parse_ok: bool = True
    parse_error: Optional[str] = None


_STRUCTURED_RX = re.compile(r"<structured>\s*(\{.*?\})\s*</structured>",
                            re.DOTALL | re.IGNORECASE)


def _split_markdown_and_structured(raw: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Pull out the JSON block. Returns (clean_markdown, parsed_json_or_None).
    The JSON block is stripped from the returned markdown so users don't see it."""
    m = _STRUCTURED_RX.search(raw or "")
    if not m:
        return raw, None
    json_blob = m.group(1)
    # Clean markdown = original minus the structured block
    md = (raw[:m.start()] + raw[m.end():]).strip()
    # Strip a trailing "---" separator if present
    md = re.sub(r"\n*-{3,}\s*$", "", md).rstrip()
    try:
        parsed = json.loads(json_blob)
        return md, parsed
    except Exception as exc:
        log.warning("structured JSON parse failed: %s", exc)
        return md, None


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from a concall PDF. Uses pypdf (pure Python)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        chunks = []
        for page in reader.pages:
            try:
                txt = page.extract_text() or ""
                if txt:
                    chunks.append(txt)
            except Exception:
                continue
        return "\n\n".join(chunks)
    except Exception as exc:
        log.warning("PDF extraction failed: %s", exc)
        return ""


class ConcallAgent:
    def __init__(self):
        self._client = None
        if ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            except Exception as exc:
                log.warning("anthropic client init failed: %s", exc)

    @property
    def available(self) -> bool:
        return self._client is not None

    def analyze(self, payload: ConcallInput) -> ConcallAnalysis:
        """Run the full analysis. Returns ConcallAnalysis with markdown + structured fields."""
        if not self.available:
            return ConcallAnalysis(markdown=self._stub(payload),
                                   parse_ok=False, parse_error="no anthropic key")

        # Cap transcript at ~140k chars (~35k tokens) to stay well under model limits
        text = payload.transcript_text or ""
        if len(text) > 140_000:
            text = text[:140_000] + "\n\n[... transcript truncated ...]"

        user_block = (
            f"Analyze the {payload.quarter} concall transcript for "
            f"**{payload.company_name} ({payload.ticker})**.\n\n"
        )
        if payload.prior_call_summary:
            user_block += ("## Summary of the PRIOR quarter's concall (for delta analysis)\n"
                          f"{payload.prior_call_summary}\n\n")
        user_block += "## Concall transcript\n```\n" + text + "\n```"

        try:
            resp = self._client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=4000,
                system=[{"type": "text", "text": CONCALL_SYSTEM,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user",
                           "content": [{"type": "text", "text": user_block}]}],
            )
            parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            raw = "\n".join(parts).strip()
            if not raw:
                return ConcallAnalysis(markdown=self._stub(payload),
                                       parse_ok=False, parse_error="empty response")
            md, parsed = _split_markdown_and_structured(raw)
            if parsed is None:
                return ConcallAnalysis(markdown=md or raw, parse_ok=False,
                                       parse_error="structured JSON missing/invalid")
            return ConcallAnalysis(
                markdown=md or raw,
                tone=parsed.get("tone"),
                net_assessment=parsed.get("net_assessment"),
                call_date=parsed.get("call_date"),
                guidance=parsed.get("guidance") or [],
                concerns=parsed.get("concerns") or [],
                positives=parsed.get("positives") or [],
                pressure_points=parsed.get("pressure_points") or [],
                verbatim_quotes=parsed.get("verbatim_quotes") or [],
                parse_ok=True,
            )
        except Exception as exc:
            log.warning("concall analysis failed: %s", exc)
            return ConcallAnalysis(markdown=f"_Concall analysis failed: {exc}_\n\n"
                                   + self._stub(payload),
                                   parse_ok=False, parse_error=str(exc))

    def analyze_and_persist(self, payload: ConcallInput) -> ConcallAnalysis:
        """Run analysis AND persist structured extraction to concall_history.db.
        Skipped on parse failure (we don't want garbage in the longitudinal store)."""
        result = self.analyze(payload)
        if result.parse_ok:
            try:
                from src.data.concall_archive import ConcallArchive, ConcallRecord
                rec = ConcallRecord(
                    ticker=payload.ticker, company_name=payload.company_name,
                    quarter=payload.quarter, call_date=result.call_date,
                    tone=result.tone, net_assessment=result.net_assessment,
                    guidance=result.guidance, concerns=result.concerns,
                    positives=result.positives,
                    pressure_points=result.pressure_points,
                    verbatim_quotes=result.verbatim_quotes,
                    markdown_analysis=result.markdown,
                    transcript_chars=len(payload.transcript_text or ""),
                )
                ConcallArchive().save(rec)
            except Exception as exc:
                log.warning("concall persistence failed: %s", exc)
        return result

    @staticmethod
    def _stub(p: ConcallInput) -> str:
        words = len((p.transcript_text or "").split())
        return (
            f"# {p.company_name} ({p.ticker}) Concall — {p.quarter}\n\n"
            "_Claude AI concall analysis is OFF (no ANTHROPIC_API_KEY in .env)._\n\n"
            f"Transcript loaded: ~{words:,} words extracted from PDF.\n\n"
            "To enable Claude-generated structured analysis (tone, guidance changes, "
            "key Q&A, red flags, verbatim quotes), add ANTHROPIC_API_KEY to `.env` and "
            "regenerate."
        )