"""Concall transcript analyzer.

Pipeline:
  1. User uploads concall transcript PDF (or pastes text)
  2. pypdf extracts text
  3. Claude reads transcript + structured prompt → outputs analysis

Output structure:
  - Management tone (bullish / cautious / defensive / neutral)
  - Guidance changes vs prior call
  - Key positive surprises
  - Key negative flags / concerns
  - Notable Q&A — analyst pressure points and management answers
  - Investment-relevant verbatim quotes
  - What changed vs prior call (if prior context provided)

Best transcripts sourced from:
  - screener.in: https://www.screener.in/company/{TICKER}/consolidated/ → "Documents" tab
  - AlphaStreet: https://research.alphastreet.com/
  - Company IR pages
  - BSE/NSE corporate filings
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Optional

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

## Implication for our view
2-3 bullets. Does this support BUY / ACCUMULATE / HOLD / REDUCE / AVOID? Are estimates \
likely to move? Is the multiple at risk of de-rating / re-rating?

HARD RULES:
- **No fabrication.** Only use what's in the transcript text.
- **Use the speaker's exact words** for the verbatim quote section — institutional \
clients verify these.
- If transcript is incomplete or cut off, say so at the top.
- Keep under 700 words total.
- Match Indian institutional voice: "FY26E", "Q4FY26", "guidance revised down 100bps", \
"capex spend Rs 4,500 Cr", "EBITDA margin band".
"""


@dataclass
class ConcallInput:
    ticker: str
    company_name: str
    quarter: str          # e.g. "Q4 FY26"
    transcript_text: str  # raw text from PDF extract or paste
    prior_call_summary: Optional[str] = None  # optional — for delta analysis


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

    def analyze(self, payload: ConcallInput) -> str:
        if not self.available:
            return self._stub(payload)

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
                max_tokens=3000,
                system=[{"type": "text", "text": CONCALL_SYSTEM,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user",
                           "content": [{"type": "text", "text": user_block}]}],
            )
            parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            return "\n".join(parts).strip() or self._stub(payload)
        except Exception as exc:
            log.warning("concall analysis failed: %s", exc)
            return f"_Concall analysis failed: {exc}_\n\n" + self._stub(payload)

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