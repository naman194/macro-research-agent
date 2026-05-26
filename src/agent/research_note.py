"""Claude-powered research note generator.

Takes a ticker + fundamentals + filings + macro context, returns an institutional-style
research note. Uses Anthropic SDK with prompt caching to keep the long system prompt
warm across requests.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are writing a structured **information note** on a single name for a \
sophisticated institutional reader. This is NOT investment advice or a buy/sell call — it is \
descriptive analysis. The reader is an institutional participant who forms their own view.

Every note follows this exact structure:

# {COMPANY} ({TICKER}) — {ONE-LINE OBSERVATION}

**Filter status:** PASSES / BORDERLINE / FAILS our Quality+Value adjusted screen  ·  \
**Composite score:** X/100  ·  **Sector overlay:** net +/- N pts

(The status above describes what our screen output shows — it is NOT a buy/sell call.)

## Summary
3–5 bullets describing what the data shows about this name. Concrete, falsifiable, sourced. \
Each bullet ties to a number or a recent event. NO prescriptive language ("we'd buy", "good \
entry", "attractive"). Use: "data shows", "filter highlights", "screen identifies".

## Catalysts Tracked (next 2–4 quarters)
What datapoints / events would materially change the picture and by when. Include any \
management commentary or filing reference if available. Frame as "things to watch", not \
"things that will move the stock".

## Valuation Picture
- Current multiples (P/E, EV/EBITDA, P/B) vs 5y own median and sector median (factual).
- **Reverse-DCF read** (if supplied): state market-implied long-term FCF growth, the 5y \
historical growth, and the sector ceiling. Frame as "the market is paying for X% long-term \
growth; the business has delivered Y% over 5 years; sector ceiling is Z%." Then a one-line \
verdict — *cheap relative to track record* / *priced for perfection vs sector* / *fair*.
- A model scenario range (bear/base/bull) using relative-multiple or DCF assumptions — clearly \
labelled as model output, not a target price. Phrase as "if base assumptions hold, the model \
implies a range of X-Y" — never "target price ₹X".
- Implied upside % vs current price, with the explicit caveat that this is a model output \
sensitive to assumptions.

## Downside Considerations
- Top 3 risks specific to this name, ranked by probability × impact.
- Model downside-case range with assumptions. Quantify the asymmetry vs base-case range.

## Bear Considerations — Why The Data May Mislead
This section is MANDATORY. Argue the opposite case against the filter's positive signal. \
Address each supplied sector structural risk (GenAI for IT, NIM compression for Banks, USFDA \
for Pharma, EV transition for Auto, etc.) AND supplied company-specific risks. For each, mark \
as: priced in / mispriced / unaddressed.
- **Forensic findings** (if supplied): cite the *specific* top flags from the forensic report \
verbatim (e.g. "CFO/PAT 0.42 — debtor-stuffing or aggressive revenue recognition concern; \
debt CAGR 22% vs profit CAGR 4%"). If the composite score is **red or amber**, the bear case \
is not complete without addressing each red metric and stating whether it has a benign \
explanation (e.g. ongoing capex cycle, recent acquisition working through the P&L) or whether \
it should re-rate the downside.
- **Management credibility** (if supplied): if the concall credibility score is below 50, note \
the specific deterioration (tone whiplash, recurring unresolved concerns, guidance churn). \
This is a SIGNAL about the reliability of the bull thesis, not just a side note.
If the historical valuation band may no longer be a valid anchor (e.g. sector PE re-rating \
lower structurally), say so explicitly. End with: "Filter status would shift if …" with 2 \
concrete triggers.

## Bull Considerations — What Would Validate The Filter Signal
This section is also MANDATORY. List supplied sector + company catalysts — for each, note \
(a) probability it materializes in next 12 months, (b) earnings/multiple impact if it does. \
End with: "Composite score would strengthen if …" with 2 concrete triggers (be specific).

## Macro & Policy Context
Two parts:
1. How the current macro setup (US Fed, India rates/INR, oil) bears on this name's sector.
2. Sector-specific policy items — quote any recent RBI/SEBI press release that touches this \
sector, with URL.

## News & Sentiment Read
Use the GDELT sentiment block: state article-count trend and mean tone. Flag any top headline \
that materially affects the picture (positive or negative).

## Disclaimer
Reproduce verbatim: "**This note is informational analysis, NOT investment advice or a \
recommendation to buy, sell or hold any security. The author is not a SEBI-registered Research \
Analyst or Investment Adviser. Composite scores, scenario ranges, and structural overlay are \
model outputs — verify independently against primary sources (annual reports, exchange \
filings) before any action. Past performance is not indicative of future results.**"

Hard rules:
- Never fabricate numbers. If a datapoint is missing, write "n/a — verify in latest filing".
- Cite the source for any specific number ("screener.in", "Q3 FY26 results", "RBI Bulletin \
Apr 2026", "GDELT tone").
- If GDELT mean tone is strongly negative (< -3) or news flow has a litigation/regulatory \
theme, surface that in Downside Considerations.
- Keep the entire note under 800 words.
- **OBSERVATIONAL TONE — NOT PRESCRIPTIVE.** Most important rule. Use: "data shows", "filter \
identifies", "screen output highlights", "the setup suggests", "model implies". NEVER use: \
"we recommend", "we prefer", "buy", "sell", "we'd add", "we'd avoid", "top pick", "high \
conviction", "go long", "take a position", "size at X%", "target price ₹X" (use "model scenario \
range" instead), "asymmetry favors going long".
- The reader is sophisticated. Present data + structural analysis + bear/bull considerations \
— they form their own conclusion.
- If you find yourself writing a verb like "buy", "sell", or "recommend" anywhere, rewrite \
the sentence.
"""


@dataclass
class ResearchInput:
    ticker: str
    fundamentals: Dict[str, Any]
    filings: List[Dict[str, Any]]
    macro_context: Dict[str, Any]
    quote: Optional[Dict[str, Any]] = None
    sentiment: Optional[Dict[str, Any]] = None       # GDELT payload
    policy_items: Optional[List[Dict[str, Any]]] = None  # RBI + SEBI items
    special_situations: Optional[List[Dict[str, Any]]] = None  # event rows for this ticker
    # Phase 3 — depth signals from the new modules
    forensic_report: Optional[Dict[str, Any]] = None       # composite, verdict, top flags
    reverse_dcf_report: Optional[Dict[str, Any]] = None    # implied growth vs historical
    concall_credibility: Optional[Dict[str, Any]] = None   # management track-record summary


class ResearchAgent:
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

    def generate(self, payload: ResearchInput) -> str:
        if not self.available:
            return self._stub_note(payload)

        user_block = self._format_user_block(payload)

        try:
            resp = self._client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=2000,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": user_block}],
                    }
                ],
            )
            parts = []
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    parts.append(block.text)
            return "\n".join(parts).strip() or self._stub_note(payload)
        except Exception as exc:
            log.warning("Claude generation failed: %s", exc)
            return f"_Research note generation failed: {exc}_\n\n" + self._stub_note(payload)

    @staticmethod
    def _format_user_block(p: ResearchInput) -> str:
        # Inject BOTH sector + company-specific structural risks AND catalysts
        from src.config import TICKER_SECTOR_MAP
        from src.data.catalysts import catalysts_as_prompt_block
        from src.data.structural_risks import risks_as_prompt_block
        sector = (p.fundamentals.get("sector")
                  or TICKER_SECTOR_MAP.get(p.ticker.upper()))
        struct_block = risks_as_prompt_block(sector=sector, ticker=p.ticker)
        cat_block = catalysts_as_prompt_block(sector=sector, ticker=p.ticker)

        sections = [
            f"Generate a research note for ticker **{p.ticker}**.",
            "",
            "## Structural risks — Bear Thesis MUST address every item below",
            "(Two layers: sector-wide risks apply to all peers; the name-specific "
            "overlay is where this stock differs from peers. Address each item — "
            "say whether it's priced in, mispriced, or unaddressed.)",
            "",
            struct_block,
            "",
            "## Positive catalysts — Bull Triggers section MUST address every item below",
            "(For each catalyst: probability it materializes in next 12 months + "
            "earnings / multiple impact if it does. Bull case requires evidence, not hope.)",
            "",
            cat_block,
            "",
            "## Fundamentals (from screener.in)",
            "```json", json.dumps(p.fundamentals, indent=2, default=str), "```",
            "",
            "## Recent corporate events (NSE, upcoming + last 90d)",
            "```json", json.dumps(p.filings[:15], indent=2, default=str), "```",
            "",
            "## Live quote",
            "```json", json.dumps(p.quote or {}, indent=2, default=str), "```",
            "",
            "## Macro context (latest)",
            "```json", json.dumps(p.macro_context, indent=2, default=str), "```",
        ]
        if p.sentiment:
            sections += [
                "",
                "## GDELT news sentiment (last 14 days)",
                "```json", json.dumps(p.sentiment, indent=2, default=str), "```",
            ]
        if p.policy_items:
            sections += [
                "",
                "## Recent RBI / SEBI policy items (latest 25)",
                "```json", json.dumps(p.policy_items[:25], indent=2, default=str), "```",
            ]
        if p.special_situations:
            sections += [
                "",
                "## Active special-situation events for this ticker",
                "```json", json.dumps(p.special_situations, indent=2, default=str), "```",
            ]
        if p.forensic_report:
            sections += [
                "",
                "## Forensic / earnings-quality scan (composite 0-100, higher = more concern)",
                "Cite the *specific red flags* verbatim in **Bear Considerations**. "
                "If the composite is red or amber, the bear case must explain each red metric.",
                "```json", json.dumps(p.forensic_report, indent=2, default=str), "```",
            ]
        if p.reverse_dcf_report:
            sections += [
                "",
                "## Reverse-DCF — what the market is paying for",
                "Use this in **Valuation Picture**. State the implied growth, vs the 5y "
                "historical reference, vs the sector ceiling, and the verdict (cheap / fair "
                "/ stretched).",
                "```json", json.dumps(p.reverse_dcf_report, indent=2, default=str), "```",
            ]
        if p.concall_credibility:
            sections += [
                "",
                "## Concall — management credibility (longitudinal)",
                "If credibility_score is < 50, surface the specific deterioration in **Bear "
                "Considerations** (tone whiplash / recurring concerns / guidance churn). "
                "If ≥ 70 and there's a bull catalyst tied to management execution, this is "
                "supporting evidence in **Bull Considerations**.",
                "```json", json.dumps(p.concall_credibility, indent=2, default=str), "```",
            ]
        sections += [
            "",
            "Produce the note. Apply the hard rules. If a critical datapoint is missing, "
            "name it and proceed with the rest.",
        ]
        return "\n".join(sections)

    @staticmethod
    def _stub_note(p: ResearchInput) -> str:
        f = p.fundamentals or {}
        return (
            f"# {f.get('name', p.ticker)} ({p.ticker}) — Research note unavailable\n\n"
            "_ANTHROPIC_API_KEY is not set. Add it to `.env` to enable Claude-generated notes._\n\n"
            "## Raw fundamentals\n"
            f"- Market cap (Cr): {f.get('market_cap_cr')}\n"
            f"- P/E: {f.get('pe')}\n"
            f"- ROCE: {f.get('roce')}%\n"
            f"- ROE: {f.get('roe')}%\n"
            f"- D/E: {f.get('debt_to_equity')}\n"
            f"- 3y sales growth: {f.get('sales_growth_3y')}%\n"
            f"- 3y profit growth: {f.get('profit_growth_3y')}%\n"
            f"- Dividend yield: {f.get('dividend_yield')}%\n\n"
            f"## Recent filings ({len(p.filings)} in last 90d)\n"
            + "\n".join(f"- {a.get('datetime','')[:10]} — {a.get('subject','')}"
                       for a in p.filings[:10])
        )
