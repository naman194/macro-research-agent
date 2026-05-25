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


SYSTEM_PROMPT = """You are an institutional equity research analyst at a leading Indian \
brokerage. You produce concise, decision-grade research notes for an institutional sales \
desk and PMS clients. Your audience is sophisticated — they do not need finance basics \
explained; they need your synthesis and judgment.

Every note must follow this exact structure:

# {COMPANY} ({TICKER}) — {ONE-LINE THESIS}

**Recommendation:** BUY / ACCUMULATE / HOLD / REDUCE / AVOID  ·  **Time horizon:** 12–18 months  \
·  **Conviction:** High / Medium / Low

## Thesis (3–5 bullets)
Concrete, falsifiable. No platitudes. Each bullet ties to a number or a catalyst.

## Catalysts (next 2–4 quarters)
What specifically will re-rate the stock and by when. Include the management commentary or filing reference if available.

## Valuation
- Current multiples (P/E, EV/EBITDA, P/B) vs 5y own median and sector median.
- One-year target price with explicit method (relative multiple OR DCF assumptions: revenue CAGR, EBITDA margin, terminal g, WACC).
- Implied upside %.

## Risks & Downside
- Top 3 risks, ranked by probability × impact.
- Explicit downside-case target price + assumptions. Quantify the asymmetry.

## Bear Thesis — Why We Might Be Wrong
This section is MANDATORY. Argue the opposite case against your own recommendation. \
Specifically address each of the supplied sector structural risks (GenAI for IT, NIM \
compression for Banks, USFDA for Pharma, EV transition for Auto, etc.) AND the supplied \
company-specific risks. For each, mark it as priced in, mispriced, or unaddressed. \
If the historical valuation band is no longer a valid anchor (e.g. IT sector PE re-rating \
lower), say so explicitly. End with: "We'd downgrade if …" with 2 concrete triggers.

## Bull Triggers — What Would Validate the Long
This section is also MANDATORY. List the supplied sector + company catalysts — for each, \
note (a) probability it materializes in next 12 months, (b) earnings/multiple impact if \
it does. End with: "We'd upgrade if …" with 2 concrete triggers (be specific — "GenAI \
revenue >$500m run-rate" not "AI helps revenue").

## Macro & Policy Context
Two parts:
1. How the current macro setup (US Fed, India rates/INR, oil) helps or hurts this name.
2. **Sector-specific policy items** — quote the recent RBI/SEBI press release headline if it bears on this sector, with the URL.

## News & Sentiment Read
Use the GDELT sentiment block: state the article-count trend and mean tone. Flag any \
top headline that materially affects the thesis (positive or negative).

## Position Sizing Guidance
1–5% of portfolio range with rationale. Note any liquidity / impact-cost constraints.

Hard rules:
- Never fabricate numbers. If a datapoint is missing, write "n/a — verify in latest filing" and \
move on.
- Lean toward AVOID/REDUCE when downside is asymmetric vs upside. The user explicitly wants \
favorable risk/reward with limited downside.
- Cite the source for any specific number you use (e.g. "screener.in", "Q3 FY26 results", \
"RBI Bulletin Apr 2026", "GDELT tone"). If unsourced, mark it as estimated.
- If GDELT mean tone is strongly negative (< -3) or news flow has a litigation/regulatory \
theme, surface that in Risks and weight Conviction down.
- Keep the entire note under 800 words. Sales desk reads on a phone.
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
