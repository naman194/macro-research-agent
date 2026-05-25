"""Claude-powered daily institutional morning note.

Gathers a snapshot of everything that matters for the start of the trading day:
  - Macro state (FRED + IMF + World Bank summary)
  - Top 3 ideas from Quality+Value and GARP screens
  - Top special-situation events with proximity <= 30 days
  - Latest 10 RBI press releases + 10 SEBI circulars
  - GDELT sentiment for 5 standard macro themes

Hands it all to Claude as a single prompt → returns a structured one-page brief
ready to send to an institutional sales desk / PMS clients.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List

import pandas as pd

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, DEFAULT_UNIVERSE
from src.data.deals import DealsAdapter
from src.data.econ_calendar import EconCalendarAdapter
from src.data.flows import FlowsAdapter
from src.data.fno import FnoAdapter
from src.data.fred import FredAdapter
from src.data.gdelt import GDELTAdapter
from src.data.imf import IMFAdapter
from src.data.index_rebalance import IndexRebalanceAdapter
from src.data.insider import InsiderAdapter
from src.data.policy import RBIAdapter, SEBIAdapter
from src.data.prices import PricesAdapter
from src.data.worldbank import WorldBankAdapter
from src.screens.garp import GARPScreener
from src.screens.quality_value import QualityValueScreener
from src.screens.special_situations import SpecialSituationsScreener
from src.screens.swing_setups import SwingScanner

log = logging.getLogger(__name__)


DAILY_NOTE_SYSTEM = """You are the lead author of the morning-meeting note at a top \
Indian institutional brokerage. Your audience is FII / DII desks, PMS managers, and HNI \
sales — sophisticated, time-pressed. The note goes out **before market open** and must \
read as if a senior research head wrote it: opinionated, sourced, actionable.

OUTPUT FORMAT (Markdown, this exact structure, this order):

# India Morning Brief — {DATE}

## At a Glance
3-4 lines. Yesterday's Nifty close + % move, breadth read, FII vs DII positioning, what \
overnight set up (US close, Asia open, oil, INR), single most important datapoint today, \
one-line "what we'd do today" view.

## Pre-Market Cues
- 4-6 bullets: each cue with **level, change, implication** (e.g. "S&P 500 +0.37% — \
risk-on overnight, mild positive for IT/Pharma ADR-correlated names").
- Cover: US (S&P/Nasdaq), Asia (Nikkei, Hang Seng), Oil (Brent/WTI), Gold, USD/INR, US 10Y, VIX.
- End with a one-line **signal**: risk-on / risk-off / neutral.

## Market Action — Yesterday
- Nifty, Sensex, Bank Nifty close + % move (cite from supplied data).
- Sectoral leaders / laggards (top 2 each by % move).
- Breadth: advance/decline ratio.
- **FII/DII flows** — quote the supplied Rs Cr numbers explicitly. Identify a divergence \
(e.g. "DII absorbed FII selling — typical support pattern").

## Top Gainers / Losers (from our universe)
A small table: 5 gainers + 5 losers with ticker, close, % change. Use markdown table syntax.

## Top Fundamental Ideas Today
Pick 2-3 highest-conviction names from the Quality+Value and GARP screen outputs supplied. \
**IMPORTANT:** Each pick has both a `raw_score` (quantitative) and `score` (structural-risk-adjusted). \
The adjusted score factors in sector disruption risks (GenAI for IT, NIM for Banks, USFDA for Pharma \
etc.) — **rank by adjusted score, not raw score**. A high raw_score with large structural_penalty \
means the financial profile looks great but the sector is facing headwinds — flag this explicitly.

For each pick, 4-5 lines:
**TICKER (Sector) — one-line thesis**
- Numbers: P/E, ROCE, 3y growth, mcap (cite from supplied data).
- Catalyst / why now.
- **Bear consideration** — the single biggest structural risk for this name's sector, and why we \
think this name is/isn't more resilient than peers.
- Entry range + downside stop guidance.

Bias toward favorable risk/reward with limited downside. If no name meets the bar after the \
structural overlay, say "no high-conviction adds today" — never force ideas just because raw \
financials look good.

## Top Technical / Swing Setups
From the supplied swing scanner output, list up to 3 trades. For each one line:
**TICKER — Setup: Entry / SL / T1 / T2 / R:R x.x · risk x.x%**
plus 1 line justification (trend filter satisfied, why this pullback / breakout is clean).
If the scanner says regime is risk-off, **say so explicitly** and recommend trimming positions, \
not adding longs.

## F&O / Derivatives Read
- Index PCR levels (Nifty / BankNifty / FinNifty) with sentiment label.
- Max Pain strike vs spot — call out if max pain is >2% away from spot (gravitational risk).
- Highest OI strikes = support / resistance levels for the week.
- One-line directional view from the OI structure.

## Smart Money Tracker
- **Block deals (yesterday):** highlight 1-2 large institutional prints from the supplied list. \
Format: "TICKER — Mutual Fund/Insurance/FII bought/sold X Cr · context if it matters".
- **Promoter activity (last 14 days):** call out any meaningful promoter BUYS (always high \
signal) and any large promoter SELLS (size matters, ESOPs already excluded). \
If none in the data, say "no notable promoter activity this week".

## Stock in Focus
Use the supplied stock-in-focus payload (which is the highest-scoring screen candidate today). \
Render the markdown block exactly as supplied — it has snapshot, valuation table, and chart \
embed marker `{IMG:focus_chart}`. Add 2-3 lines AFTER the supplied block on:
- Why this name vs others (the screen score advantage in plain English)
- One specific catalyst (results, capex, sector rotation)
- Position-sizing guidance (1-3% of portfolio range)

## Macro Calendar — Next 14 Days
List the high-importance events from the supplied calendar payload first (RBI MPC, Fed FOMC, \
India CPI, GDP). One line each. End with a 1-line "what we're watching most" view.

## Index Rebalance Watch
If the supplied rebalance payload has likely_additions or likely_deletions, mention 1-2 \
highest-conviction names with the passive-flow estimate. If none, skip this section.

## Catalysts This Week
- Special-situation events from supplied list — buybacks, bonus, splits, fund-raising — \
prioritised by date and event weight.
- Show date, ticker, event type, one-line context. Max 6 items.

## Policy & Regulatory
- 2-3 bullets distilling supplied RBI + SEBI items. Skip routine items (penalty notices, \
T-bill auctions) unless they signal a policy shift. Link the source where supplied.

## News & Sentiment Read
- For each macro theme with sentiment data, one line: theme, mean tone, article volume, \
implication.
- Flag any theme with tone < -3 (very negative) or > +3 (very positive) — that's the \
actionable signal.

## Risk Watch
- 2-3 bullets on what could derail today / this week. Be specific, not generic \
("Brent above $90 hurts paint/aviation margins" — not "geopolitical risk").

## Disclaimer
One-line: "For institutional use only. Not investment advice. Sources: yfinance OHLCV, NSE \
provisional flows, NSE corporate events feed, screener.in fundamentals, FRED/IMF/WB macro, \
RBI/SEBI public filings, GDELT news sentiment — verify all figures before action."

HARD RULES:
- **Never fabricate.** If a number isn't in the supplied data, write "n/a — verify" or omit. \
Do not invent FII figures, sectoral moves, or company news.
- **Cite specifically** when you use a number — readers must be able to verify.
- **Keep under 900 words total.** Morning note, not research report.
- **Be opinionated.** "We prefer", "we'd avoid", "the asymmetry favors". Hedging language \
("could potentially") loses the desk's respect.
- **Match Indian institutional voice.** Standard terms: SGX Nifty (now GIFT Nifty), MPC, \
GST, CPI, IIP, Cr/Lakh Cr, bps.
- If there are no quality ideas to surface, say "No conviction adds today; we'd let the tape \
settle" — better than forcing weak ideas.
- For technical/swing setups, if regime is risk-off, **do not recommend long entries** — \
recommend defensive posture.
"""


@dataclass
class DailyNoteData:
    today: str
    macro_fred: List[Dict[str, Any]]
    macro_imf: List[Dict[str, Any]]
    macro_wb: List[Dict[str, Any]]
    indices_snapshot: List[Dict[str, Any]]
    global_cues: List[Dict[str, Any]]
    fii_dii: List[Dict[str, Any]]
    gainers: List[Dict[str, Any]]
    losers: List[Dict[str, Any]]
    breadth: Dict[str, Any]
    top_quality_value: List[Dict[str, Any]]
    top_garp: List[Dict[str, Any]]
    swing_setups: Dict[str, Any]
    special_situations: List[Dict[str, Any]]
    rbi_items: List[Dict[str, Any]]
    sebi_items: List[Dict[str, Any]]
    theme_sentiment: List[Dict[str, Any]]
    # Phase P0 additions
    block_deals: List[Dict[str, Any]] = field(default_factory=list)
    institutional_bulk_deals: List[Dict[str, Any]] = field(default_factory=list)
    promoter_buys: List[Dict[str, Any]] = field(default_factory=list)
    promoter_sells: List[Dict[str, Any]] = field(default_factory=list)
    fno_signals: List[Dict[str, Any]] = field(default_factory=list)
    # Phase P1 additions
    econ_calendar: List[Dict[str, Any]] = field(default_factory=list)
    rebalance_predictions: Dict[str, Any] = field(default_factory=dict)
    stock_in_focus: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


THEMES = ["India economy", "RBI monetary policy", "Indian rupee",
          "FII outflows", "Indian banks", "India inflation"]


def _safe(loader, label: str, errors: List[str], default):
    try:
        return loader()
    except Exception as exc:
        log.warning("daily-note source %s failed: %s", label, exc)
        errors.append(f"{label}: {exc}")
        return default


def gather() -> DailyNoteData:
    """Gather every input the agent needs. Each source is wrapped — if any one fails,
    the note still generates with the rest. Errors are surfaced in the payload."""
    errors: List[str] = []

    def _fred():
        df = FredAdapter().snapshot()
        return df.to_dict("records") if not df.empty else []

    def _imf():
        df = IMFAdapter().latest_table()
        return df[df["country"].isin(["IND", "USA", "CHN"])].to_dict("records") if not df.empty else []

    def _wb():
        df = WorldBankAdapter().latest_table()
        return df[df["country"].isin(["IN", "US", "CN"])].to_dict("records") if not df.empty else []

    def _qv():
        res = QualityValueScreener().run(list(DEFAULT_UNIVERSE))
        return res.candidates.head(5).to_dict("records") if not res.candidates.empty else []

    def _garp():
        res = GARPScreener().run(list(DEFAULT_UNIVERSE))
        return res.candidates.head(5).to_dict("records") if not res.candidates.empty else []

    def _special():
        res = SpecialSituationsScreener().run([])
        if res.candidates.empty:
            return []
        df = res.candidates
        return df[df["days_out"].fillna(99) <= 30].head(15).to_dict("records")

    def _rbi():
        return RBIAdapter().press_releases(15)

    def _sebi():
        return SEBIAdapter().circulars(15)

    def _themes():
        adapter = GDELTAdapter()
        out = []
        for t in THEMES:
            try:
                tone = adapter.tone(t, timespan="14d")
                out.append({"theme": t, **{k: v for k, v in tone.items() if k != "distribution"}})
            except Exception as exc:
                log.warning("theme %s failed: %s", t, exc)
        return out

    def _indices():
        df = PricesAdapter().indices_snapshot()
        return df.to_dict("records") if not df.empty else []

    def _global():
        df = PricesAdapter().global_cues_snapshot()
        return df.to_dict("records") if not df.empty else []

    def _flows():
        return FlowsAdapter().fii_dii_latest()

    def _movers():
        return PricesAdapter().market_breadth_and_movers(list(DEFAULT_UNIVERSE))

    def _swing():
        return SwingScanner().scan(list(DEFAULT_UNIVERSE), require_market_uptrend=True)

    def _deals_summary():
        return DealsAdapter().latest_summary(top_n=8)

    def _insider_summary():
        return InsiderAdapter().latest_summary(days_back=14, top_n=8)

    def _fno():
        return FnoAdapter().headline_signals()

    def _econ():
        return EconCalendarAdapter().upcoming(lookahead_days=14)

    def _rebalance():
        return IndexRebalanceAdapter().predict_nifty50_changes()

    today = date.today().strftime("%d %b %Y")

    movers = _safe(_movers, "Movers", errors,
                   {"advances": 0, "declines": 0, "unchanged": 0, "gainers": [], "losers": []})
    deals_sum = _safe(_deals_summary, "Block/Bulk deals", errors,
                      {"block_top": [], "institutional_buys": []})
    insider_sum = _safe(_insider_summary, "Insider", errors,
                        {"promoter_buys": [], "promoter_sells": []})

    # Phase P1: stock in focus from screen winners (gather after screens)
    qv_picks = _safe(_qv, "QV screen", errors, [])
    garp_picks = _safe(_garp, "GARP screen", errors, [])
    from src.agent.stock_in_focus import build_focus  # local import to avoid circular
    sif = _safe(lambda: build_focus(qv_picks, garp_picks),
                "Stock-in-focus", errors, {})

    return DailyNoteData(
        today=today,
        macro_fred=_safe(_fred, "FRED", errors, []),
        macro_imf=_safe(_imf, "IMF", errors, []),
        macro_wb=_safe(_wb, "WorldBank", errors, []),
        indices_snapshot=_safe(_indices, "Indices", errors, []),
        global_cues=_safe(_global, "Global cues", errors, []),
        fii_dii=_safe(_flows, "FII/DII", errors, []),
        gainers=movers.get("gainers", []),
        losers=movers.get("losers", []),
        breadth={"advances": movers.get("advances", 0),
                 "declines": movers.get("declines", 0),
                 "unchanged": movers.get("unchanged", 0),
                 "adv_dec_ratio": movers.get("adv_dec_ratio")},
        top_quality_value=qv_picks,
        top_garp=garp_picks,
        swing_setups=_safe(_swing, "Swing scanner", errors,
                          {"regime": "unknown", "trend_pullback": [], "base_breakout": []}),
        special_situations=_safe(_special, "Special-sit", errors, []),
        rbi_items=_safe(_rbi, "RBI", errors, []),
        sebi_items=_safe(_sebi, "SEBI", errors, []),
        theme_sentiment=_safe(_themes, "GDELT themes", errors, []),
        block_deals=deals_sum.get("block_top", []),
        institutional_bulk_deals=deals_sum.get("institutional_buys", []),
        promoter_buys=insider_sum.get("promoter_buys", []),
        promoter_sells=insider_sum.get("promoter_sells", []),
        fno_signals=_safe(_fno, "F&O signals", errors, []),
        econ_calendar=_safe(_econ, "Econ calendar", errors, []),
        rebalance_predictions=_safe(_rebalance, "Rebalance predictor", errors, {}),
        stock_in_focus=sif,
        errors=errors,
    )


class DailyNoteAgent:
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

    def generate(self, data: DailyNoteData) -> str:
        if not self.available:
            return self._stub(data)

        user_block = self._format_user_block(data)
        try:
            resp = self._client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=2500,
                system=[{
                    "type": "text",
                    "text": DAILY_NOTE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user",
                          "content": [{"type": "text", "text": user_block}]}],
            )
            parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            return "\n".join(parts).strip() or self._stub(data)
        except Exception as exc:
            log.warning("Claude daily-note generation failed: %s", exc)
            return f"_Daily note generation failed: {exc}_\n\n" + self._stub(data)

    @staticmethod
    def _format_user_block(d: DailyNoteData) -> str:
        sections = [
            f"Write the morning brief for **{d.today}**.",
            "",
            "## Yesterday — Indian indices close",
            "```json", json.dumps(d.indices_snapshot, indent=2, default=str), "```",
            "",
            "## Pre-Market — global cues (overnight)",
            "```json", json.dumps(d.global_cues, indent=2, default=str), "```",
            "",
            "## FII / DII cash market flows (Rs Cr)",
            "```json", json.dumps(d.fii_dii, indent=2, default=str), "```",
            "",
            "## Top Gainers (from our universe)",
            "```json", json.dumps(d.gainers, indent=2, default=str), "```",
            "",
            "## Top Losers (from our universe)",
            "```json", json.dumps(d.losers, indent=2, default=str), "```",
            "",
            "## Breadth",
            "```json", json.dumps(d.breadth, indent=2, default=str), "```",
            "",
            "## Top 5 from Quality+Value screen",
            "```json", json.dumps(d.top_quality_value, indent=2, default=str), "```",
            "",
            "## Top 5 from GARP screen",
            "```json", json.dumps(d.top_garp, indent=2, default=str), "```",
            "",
            "## Technical Swing Setups (scanner output)",
            "```json", json.dumps({
                "regime": d.swing_setups.get("regime"),
                "trend_pullback_top3": d.swing_setups.get("trend_pullback", [])[:3],
                "base_breakout_top3": d.swing_setups.get("base_breakout", [])[:3],
                "methodology": d.swing_setups.get("methodology"),
            }, indent=2, default=str), "```",
            "",
            "## F&O Signals — Index Open Interest snapshot",
            "```json", json.dumps(d.fno_signals, indent=2, default=str), "```",
            "",
            "## Smart Money — Block deals yesterday (top 8)",
            "```json", json.dumps(d.block_deals, indent=2, default=str), "```",
            "",
            "## Smart Money — Institutional bulk-deal buys",
            "```json", json.dumps(d.institutional_bulk_deals, indent=2, default=str), "```",
            "",
            "## Smart Money — Promoter buys (last 14d, ESOP excluded)",
            "```json", json.dumps(d.promoter_buys, indent=2, default=str), "```",
            "",
            "## Smart Money — Promoter sells (last 14d, ESOP excluded)",
            "```json", json.dumps(d.promoter_sells, indent=2, default=str), "```",
            "",
            "## Stock in Focus (highest-scoring screen candidate)",
            "```json", json.dumps({k: v for k, v in (d.stock_in_focus or {}).items()
                                    if k not in ("chart_png", "markdown")},
                                   indent=2, default=str), "```",
            "",
            "## Upcoming macro calendar (next 14 days)",
            "```json", json.dumps(d.econ_calendar, indent=2, default=str), "```",
            "",
            "## Index rebalance predictor — likely Nifty 50 add/drop",
            "```json", json.dumps({
                "likely_additions_top5": d.rebalance_predictions.get("likely_additions", [])[:5],
                "likely_deletions": d.rebalance_predictions.get("likely_deletions", []),
            }, indent=2, default=str), "```",
            "",
            "## Macro context (FRED, supplementary)",
            "```json", json.dumps(d.macro_fred[:6], indent=2, default=str), "```",
            "",
            "## Special-situation events (next 30 days)",
            "```json", json.dumps(d.special_situations, indent=2, default=str), "```",
            "",
            "## Recent RBI press releases (latest 15)",
            "```json", json.dumps(d.rbi_items, indent=2, default=str), "```",
            "",
            "## Recent SEBI circulars (latest 15)",
            "```json", json.dumps(d.sebi_items, indent=2, default=str), "```",
            "",
            "## Macro-theme news sentiment (GDELT, 14d)",
            "```json", json.dumps(d.theme_sentiment, indent=2, default=str), "```",
        ]
        if d.errors:
            sections += [
                "",
                "## Data sources that failed (omit these from the note if relevant)",
                "\n".join(f"- {e}" for e in d.errors),
            ]
        sections += [
            "",
            "Write the morning brief now. Apply all hard rules. Keep under 700 words.",
        ]
        return "\n".join(sections)

    @staticmethod
    def _stub(d: DailyNoteData) -> str:
        """Structured brief without Claude — institutional format using only raw data.

        Reads like a desk research analyst's pre-brief: clear sections, real numbers,
        no editorial voice. Less polished than the AI version but still usable.
        """
        out = [f"# India Morning Brief — {d.today}", ""]

        # AT A GLANCE — auto-built from the indices snapshot
        out.append("## At a Glance")
        nifty = next((i for i in d.indices_snapshot if i.get("index") == "Nifty 50"), None)
        sensex = next((i for i in d.indices_snapshot if i.get("index") == "Sensex"), None)
        bn = next((i for i in d.indices_snapshot if i.get("index") == "Bank Nifty"), None)
        if nifty:
            sign = "+" if nifty["change_pct"] >= 0 else ""
            line = f"Nifty closed at **{nifty['close']:,.0f}** ({sign}{nifty['change_pct']:.2f}%)"
            if bn:
                bn_sign = "+" if bn["change_pct"] >= 0 else ""
                line += f", Bank Nifty {bn['close']:,.0f} ({bn_sign}{bn['change_pct']:.2f}%)"
            if sensex:
                sx_sign = "+" if sensex["change_pct"] >= 0 else ""
                line += f", Sensex {sensex['close']:,.0f} ({sx_sign}{sensex['change_pct']:.2f}%)."
            out.append(line)
        fii_line = next((f for f in d.fii_dii if f.get("category") in ("FII/FPI", "FII")), None)
        dii_line = next((f for f in d.fii_dii if f.get("category") == "DII"), None)
        if fii_line and dii_line:
            f_sign = "+" if fii_line["net_cr"] >= 0 else ""
            d_sign = "+" if dii_line["net_cr"] >= 0 else ""
            out.append(f"FII net **{f_sign}{fii_line['net_cr']:,.0f} Cr** · "
                       f"DII net **{d_sign}{dii_line['net_cr']:,.0f} Cr** "
                       f"({fii_line.get('date')}).")
        if d.breadth and d.breadth.get("adv_dec_ratio") is not None:
            out.append(f"Universe breadth: {d.breadth['advances']}A / {d.breadth['declines']}D "
                       f"(A/D ratio {d.breadth['adv_dec_ratio']}).")
        out.append("")

        # PRE-MARKET CUES
        out.append("## Pre-Market Cues")
        for c in d.global_cues[:10]:
            sign = "+" if c["change_pct"] >= 0 else ""
            out.append(f"- **{c['cue']}**: {c['close']:,.2f} ({sign}{c['change_pct']:.2f}%)")
        out.append("")

        # MARKET ACTION
        out.append("## Market Action — Yesterday")
        if d.indices_snapshot:
            # Sort sectoral indices by % move
            sectoral = [i for i in d.indices_snapshot
                        if i.get("index") not in ("Nifty 50", "Bank Nifty", "Sensex")]
            sectoral.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
            if sectoral:
                out.append("**Sectoral leaders / laggards:**")
                for s in sectoral[:3]:
                    sign = "+" if s["change_pct"] >= 0 else ""
                    out.append(f"- ⬆ {s['index']}: {sign}{s['change_pct']:.2f}%")
                for s in sectoral[-3:]:
                    sign = "+" if s["change_pct"] >= 0 else ""
                    out.append(f"- ⬇ {s['index']}: {sign}{s['change_pct']:.2f}%")
        out.append("")

        # GAINERS / LOSERS
        if d.gainers or d.losers:
            out.append("## Top Gainers / Losers (universe)")
            out.append("")
            out.append("| Gainers | Close | % | Losers | Close | % |")
            out.append("|---|---:|---:|---|---:|---:|")
            for i in range(min(5, max(len(d.gainers), len(d.losers)))):
                g = d.gainers[i] if i < len(d.gainers) else {}
                l = d.losers[i] if i < len(d.losers) else {}
                out.append(
                    f"| {g.get('ticker','')} | {g.get('close','')} | "
                    f"{g.get('change_pct','')}% | {l.get('ticker','')} | "
                    f"{l.get('close','')} | {l.get('change_pct','')}% |"
                )
            out.append("")

        # FUNDAMENTAL IDEAS
        out.append("## Top Fundamental Ideas Today")
        if d.top_quality_value:
            out.append("**Quality + Value picks:**")
            for c in d.top_quality_value[:3]:
                out.append(
                    f"- **{c.get('ticker')}** ({c.get('name')}) — score {c.get('score')} · "
                    f"ROCE {c.get('roce')}% · ROE {c.get('roe')}% · P/E {c.get('pe')} · "
                    f"D/E {c.get('debt_to_equity')} · 3y profit CAGR {c.get('profit_growth_3y')}%"
                )
        if d.top_garp:
            out.append("")
            out.append("**GARP picks:**")
            for c in d.top_garp[:3]:
                out.append(
                    f"- **{c.get('ticker')}** ({c.get('name')}) — score {c.get('score')} · "
                    f"PEG {c.get('peg')} · 3y profit CAGR {c.get('profit_growth_3y')}% · "
                    f"TTM {c.get('profit_growth_ttm')}%"
                )
        out.append("")

        # SWING SETUPS
        out.append("## Top Technical / Swing Setups")
        regime = d.swing_setups.get("regime", "")
        out.append(f"_Regime: {regime}_")
        out.append("")
        pulls = d.swing_setups.get("trend_pullback", [])[:3]
        if pulls:
            out.append("**Trend-Pullback (high win-rate, 1.5-2x R:R):**")
            for s in pulls:
                out.append(
                    f"- **{s['ticker']}** — Entry **{s['entry']}** / SL **{s['stop']}** / "
                    f"T1 **{s['target1']}** / T2 **{s['target2']}** · R:R **{s['risk_reward']}** · "
                    f"risk {s['risk_pct']}% · vol {s['volume_ratio']}x · RSI {s['rsi']}"
                )
        breaks = d.swing_setups.get("base_breakout", [])[:3]
        if breaks:
            out.append("")
            out.append("**Base Breakout (lower win-rate, 3-5x R:R):**")
            for s in breaks:
                out.append(
                    f"- **{s['ticker']}** — Entry **{s['entry']}** / SL **{s['stop']}** / "
                    f"T1 **{s['target1']}** / T2 **{s['target2']}** · R:R **{s['risk_reward']}** · "
                    f"vol {s['volume_ratio']}x"
                )
        if not pulls and not breaks:
            out.append("No qualifying technical setups today. Risk-off posture suggested.")
        out.append("")

        # F&O DERIVATIVES
        if d.fno_signals:
            out.append("## F&O / Derivatives Read")
            for s in d.fno_signals:
                pcr = s.get("pcr_oi")
                mp = s.get("max_pain")
                mp_d = s.get("max_pain_distance_pct")
                if pcr is None or mp is None: continue
                out.append(
                    f"- **{s['symbol']}** — spot {s.get('underlying'):,.0f} · "
                    f"PCR **{pcr:.2f}** · Max Pain **{mp:,.0f}** "
                    f"({mp_d:+.2f}% from spot) · "
                    f"Support {s.get('support'):,.0f} / Resistance {s.get('resistance'):,.0f} · "
                    f"_{s.get('sentiment')}_"
                )
            out.append("")

        # SMART MONEY
        if d.block_deals or d.promoter_buys or d.promoter_sells:
            out.append("## Smart Money Tracker")
            if d.block_deals:
                out.append("**Block deals (yesterday):**")
                for b in d.block_deals[:6]:
                    out.append(
                        f"- {b.get('symbol')} — {b.get('side')} {b.get('client','')[:40]} "
                        f"· {b.get('value_cr'):,.1f} Cr (qty {b.get('qty'):,})"
                    )
                out.append("")
            if d.promoter_buys:
                out.append("**Promoter buys (last 14d):**")
                for p in d.promoter_buys[:5]:
                    val = (f"{p.get('buy_value_cr'):,.1f} Cr"
                           if p.get('buy_value_cr') else f"qty {p.get('qty'):,}")
                    out.append(f"- {p.get('symbol')} — {p.get('acq_name','')[:35]} · {val} "
                              f"({p.get('date')})")
                out.append("")
            if d.promoter_sells:
                out.append("**Promoter sells (last 14d):**")
                for p in d.promoter_sells[:5]:
                    val = (f"{p.get('sell_value_cr'):,.1f} Cr"
                           if p.get('sell_value_cr') else f"qty {p.get('qty'):,}")
                    out.append(f"- {p.get('symbol')} — {p.get('acq_name','')[:35]} · {val} "
                              f"({p.get('date')})")
                out.append("")

        # STOCK IN FOCUS
        sif = d.stock_in_focus or {}
        if sif and "error" not in sif and sif.get("markdown"):
            out.append(sif["markdown"])
            if sif.get("chart_png"):
                out.append("{IMG:focus_chart}")
            out.append("")

        # ECON CALENDAR (next 14 days, high importance first)
        if d.econ_calendar:
            out.append("## Macro Calendar — Next 14 Days")
            for e in d.econ_calendar[:10]:
                imp = e.get("importance", "")
                flag = "🔴" if imp == "high" else "🟡" if imp == "medium" else "·"
                out.append(f"- {flag} **{e['event_date']}** · {e['country']} · "
                          f"{e['indicator']} ({e['publisher']})")
            out.append("")

        # CATALYSTS
        out.append("## Catalysts This Week")
        for e in d.special_situations[:6]:
            out.append(
                f"- **{e.get('event_date')}** — {e.get('ticker')} "
                f"({e.get('event_type')}, T-{e.get('days_out')}): {e.get('purpose')}"
            )
        out.append("")

        # POLICY
        out.append("## Policy & Regulatory")
        out.append("**RBI:**")
        for r in d.rbi_items[:5]:
            out.append(f"- [{r.get('title')}]({r.get('url')})")
        out.append("")
        out.append("**SEBI:**")
        for s in d.sebi_items[:5]:
            out.append(f"- [{s.get('title')}]({s.get('url')})")
        out.append("")

        # SENTIMENT
        out.append("## News & Sentiment Read (GDELT 14d)")
        for t in d.theme_sentiment:
            tone = t.get("mean_tone")
            flag = ""
            if tone is not None:
                if tone < -3: flag = " ⚠ very negative"
                elif tone > 3: flag = " ✓ very positive"
            out.append(f"- **{t.get('theme')}**: tone {tone}, "
                       f"{t.get('total_articles')} articles, "
                       f"{t.get('pct_positive')}% positive{flag}")
        out.append("")

        out.append("## Disclaimer")
        out.append("_For institutional use only. Not investment advice. "
                   "Sources: yfinance OHLCV, NSE provisional flows, NSE corporate events feed, "
                   "screener.in fundamentals, FRED/IMF/WB macro, RBI/SEBI public filings, "
                   "GDELT news sentiment. Verify all figures before action._")

        if d.errors:
            out.append("")
            out.append("---")
            out.append("_Data source errors during gather (note may be incomplete):_")
            for e in d.errors:
                out.append(f"- {e}")

        return "\n".join(out)
