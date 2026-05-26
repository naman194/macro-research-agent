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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

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
from src.screens.forensics import analyze as forensic_analyze
from src.screens.garp import GARPScreener
from src.screens.quality_value import QualityValueScreener
from src.screens.special_situations import SpecialSituationsScreener
from src.screens.swing_setups import SwingScanner

log = logging.getLogger(__name__)


DAILY_NOTE_SYSTEM = """You are the lead author of the morning research summary at an Indian \
institutional brokerage. Your audience is FII / DII desks, PMS managers, and HNI sales — \
sophisticated, time-pressed. This document is **informational analysis**, NOT investment \
recommendations. You describe what the data + screens + structural overlay show. The reader \
decides what to do with it.

OUTPUT FORMAT (Markdown, this exact structure, this order):

# India Morning Brief — {DATE}

## At a Glance
3-4 lines. Yesterday's Nifty close + % move, breadth read, FII vs DII positioning, what \
overnight set up (US close, Asia open, oil, INR), single most important datapoint today, \
one-line "what to watch" observation. NEVER use language like "we recommend", "buy here", \
"avoid this". Use observational language: "the setup suggests", "data shows", "tape implies".

## Pre-Market Cues
- 4-6 bullets: each cue with **level, change, implication** (e.g. "S&P 500 +0.37% — \
positive overnight tone, historically correlated with IT/Pharma ADR moves").
- Cover: US (S&P/Nasdaq), Asia (Nikkei, Hang Seng), Oil (Brent/WTI), Gold, USD/INR, US 10Y, VIX.
- End with a one-line **regime observation**: risk-on / risk-off / neutral (based on data, \
not a recommendation).

## Market Action — Yesterday
- Nifty, Sensex, Bank Nifty close + % move (cite from supplied data).
- Sectoral leaders / laggards (top 2 each by % move).
- Breadth: advance/decline ratio.
- **FII/DII flows** — quote the supplied Rs Cr numbers explicitly. Describe divergences \
factually (e.g. "DII absorbed FII selling — historically a support pattern, not always reliable").

## Top Gainers / Losers (from our universe)
A small table: 5 gainers + 5 losers with ticker, close, % change. Use markdown table syntax.

## Names Passing Our Quality+Value / GARP Filters
Show the 2-3 highest-scoring names from the supplied screen output. **IMPORTANT:** Each name \
has `raw_score` (quantitative) and `score` (structural-risk-adjusted). The adjusted score factors \
in sector disruption risks (GenAI for IT, NIM for Banks, USFDA for Pharma etc.) — **rank by \
adjusted score, not raw score**. A high raw_score with large structural_penalty means the \
financial profile looks attractive but the sector faces headwinds — flag this explicitly.

EACH name in the supplied data has structured fields the buyside reader cares about:
- `conviction_signals`: list of independent confirms. Possible values:
  - `qv` / `garp` — the primary screen that surfaced the name
  - `qv_also` / `garp_also` — the *other* screen ALSO surfaced this name (strong cross-screen confirm)
  - `forensic_clean` — earnings-quality battery shows no red flags
  - `forensic_amber` — minor flags (informational, weaker than clean)
  - `dcf_cheap` — reverse-DCF implies the market is paying for *less* growth than the business has delivered
  - `momentum_pos` — 90-day relative strength vs Nifty is positive
  - `smart_money_buy` — appears in last 14d promoter buys OR institutional bulk buys
  - `special_sit` — has an active special-situation event (buyback / fund-raising / etc.)
- `conviction_count`: how many of the above are firing simultaneously (1 = single signal, 4+ = multi-confirm)
- `delta_status`: "new_today" (first appearance) or "persistent" (carried over from prior brief)
- `days_in_brief`: how many consecutive briefs this ticker has appeared on

Surface these inline. Format:

**TICKER (Sector) ⭐⭐⭐ 4-signal · 🆕 NEW today** — one-line observational summary
**TICKER (Sector) ⭐⭐ 2-signal · 📌 Day 5 in brief** — one-line observational summary

Use ⭐ count = conviction_count (cap visual at 5). Use 🆕 NEW for delta_status='new_today'; \
use 📌 Day N for delta_status='persistent' with days_in_brief.

Then 4-5 lines:
- **Conviction reads**: list the conviction_signals as a short comma-separated string, e.g. \
"qv pass · forensic clean · DCF cheap · 90d RS positive". This is the buyside read of \
*independent signals agreeing*.
- Filter result: **passes Q+V / GARP screen** (adjusted score X/100, raw score Y, structural \
penalty Z).
- Key fundamentals: P/E, ROCE, 3y growth, mcap (cite from data).
- Why the screen highlights this name: catalyst / mechanical reason.
- **Considerations against** — the biggest structural risk for this name's sector. Note \
whether this name appears more/less exposed than peers based on supplied flags.

If no name passes the adjusted filter today, say "No names passed today's adjusted-score filter" \
— do not force entries.

PRIORITIZE names with conviction_count ≥ 3 — those are the multi-signal-aligned. A name with \
conviction_count=1 (just appears in the screen) is informational; a name with conviction_count=4+ \
is where independent methods agree.

**DO NOT use words like "buy", "recommend", "we'd add", "top pick", "high conviction".** \
Use: "passes filter", "ranks highest", "data highlights", "structural setup shows", \
"multi-signal aligned", "independent confirms".

## Technical Setups Observed
From the supplied swing scanner output, list up to 3 setups. For each one line:
**TICKER — Setup observed: Entry ₹X · Stop ₹Y · Target ₹Z · R:R x.x · risk x.x%**
plus 1 line of factual context (e.g. "trend-pullback filter triggered: price reclaimed 20DMA \
with RSI rising and OBV positive").
If the scanner reports risk-off regime, state that factually — note that no long setups fired, \
which historically correlates with defensive posture by trend-following systems. Do not advise \
action.

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

## Spotlight — Name in Focus
Use the supplied spotlight payload (the highest-scoring screen candidate today). Render the \
markdown block exactly as supplied — it has the snapshot, scenario range table, and chart \
embed marker `{IMG:focus_chart}`. Add 2-3 lines AFTER the supplied block on:
- What separates this name in the screen output (factual score comparison)
- One specific upcoming catalyst (results date, capex announcement, sector data point)
- A reminder that scenario-range values are model outputs, not price targets

DO NOT include "position-sizing guidance" or "recommended size" — those are recommendations.

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
- **If the supplied Forensic Watch payload is non-empty, add one bullet from it.** \
Format: "**TICKER** — *specific red flag from `top_flags`* (forensic score X/100)". \
This surfaces accounting-quality concerns on names the *screens love* or that *fell \
yesterday* — not a sell signal, a "open the annual report before any action" call. \
Skip if the payload is empty.

## Disclaimer
Reproduce verbatim: "**This document is informational analysis, NOT investment advice or a \
recommendation to buy, sell or hold any security. The author is not a SEBI-registered Research \
Analyst or Investment Adviser. Filter outputs, scenario ranges, and structural overlay scores \
are model outputs — verify independently against primary sources before any action. Past \
performance is not indicative of future results. Sources: yfinance OHLCV, NSE provisional flows, \
NSE corporate events feed, screener.in fundamentals, FRED/IMF/WB macro, RBI/SEBI public filings, \
GDELT news sentiment.**"

HARD RULES:
- **Never fabricate.** If a number isn't in the supplied data, write "n/a — verify" or omit.
- **Cite specifically** when you use a number — readers must be able to verify.
- **Keep under 900 words total.** Morning brief, not research report.
- **OBSERVATIONAL TONE — NOT PRESCRIPTIVE.** This is the most important rule. Use: "data shows", \
"filter highlights", "screen output identifies", "tape implies", "structural setup suggests". \
NEVER use: "we recommend", "we prefer", "buy", "sell", "we'd avoid", "top pick", "conviction \
add", "go long", "take a position", "size at X%", "target price". The reader is a sophisticated \
institutional participant — present the data and analysis, they form their own view.
- **Match Indian institutional voice.** Standard terms: GIFT Nifty, MPC, GST, CPI, IIP, Cr/Lakh \
Cr, bps.
- If there are no names passing filters, say "No names passed today's adjusted-score filter" — \
do not force entries.
- For technical setups in risk-off regime, state that no long setups fired and note historical \
correlation with defensive posture by trend-following systems. Do not advise action.
- The word "**recommend**" and the words "**buy**", "**sell**", "**hold**" as imperatives \
NEVER appear in the output. If you find yourself writing them, rewrite the sentence.
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
    # Phase 3 — forensic watch
    forensic_watch: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


THEMES = ["India economy", "RBI monetary policy", "Indian rupee",
          "FII outflows", "Indian banks", "India inflation"]


def _safe(loader, label: str, errors: List[str], default, lock: Optional[threading.Lock] = None):
    """Run loader, returning default + recording error on failure.
    Pass `lock` when called from a thread-pool to make errors-list append safe."""
    try:
        return loader()
    except Exception as exc:
        log.warning("daily-note source %s failed: %s", label, exc)
        if lock:
            with lock:
                errors.append(f"{label}: {exc}")
        else:
            errors.append(f"{label}: {exc}")
        return default


def gather(progress: Optional[Callable[[str], None]] = None,
           max_workers: int = 8) -> DailyNoteData:
    """Gather every input the agent needs. Phase 1 (~20 independent loaders)
    runs in a thread pool; Phase 2 (forensic_watch + stock_in_focus, which
    need Phase 1 outputs) runs sequentially after.

    `progress(label)` is called once per Phase 1 task completion + once per
    Phase 2 step. Wire it to `st.status()` for live stepped UI.
    """
    errors: List[str] = []
    errors_lock = threading.Lock()

    def _step(label: str) -> None:
        if progress is not None:
            try:
                progress(label)
            except Exception:
                pass

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

    # ====================================================================
    # Phase 1 — independent loaders run in parallel
    # ====================================================================
    phase1_jobs = {
        "FRED":              (_fred, []),
        "IMF":               (_imf, []),
        "WorldBank":         (_wb, []),
        "Indices":           (_indices, []),
        "Global cues":       (_global, []),
        "FII/DII flows":     (_flows, []),
        "Movers":            (_movers, {"advances": 0, "declines": 0,
                                          "unchanged": 0, "gainers": [], "losers": []}),
        "Swing setups":      (_swing, {"regime": "unknown", "trend_pullback": [],
                                        "base_breakout": []}),
        "Block/Bulk deals":  (_deals_summary, {"block_top": [], "institutional_buys": []}),
        "Insider":           (_insider_summary, {"promoter_buys": [], "promoter_sells": []}),
        "F&O signals":       (_fno, []),
        "Econ calendar":     (_econ, []),
        "Rebalance":         (_rebalance, {}),
        "RBI":               (_rbi, []),
        "SEBI":              (_sebi, []),
        "GDELT themes":      (_themes, []),
        "Q+V screen":        (_qv, []),
        "GARP screen":       (_garp, []),
        "Special-sit":       (_special, []),
    }

    phase1: Dict[str, Any] = {}
    _step(f"Starting {len(phase1_jobs)} parallel data pulls…")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_to_label = {
            ex.submit(_safe, loader, label, errors, default, errors_lock): label
            for label, (loader, default) in phase1_jobs.items()
        }
        done = 0
        for fut in as_completed(fut_to_label):
            label = fut_to_label[fut]
            phase1[label] = fut.result()
            done += 1
            _step(f"✓ {label} ({done}/{len(phase1_jobs)})")

    movers = phase1["Movers"]
    deals_sum = phase1["Block/Bulk deals"]
    insider_sum = phase1["Insider"]
    qv_picks = phase1["Q+V screen"]
    garp_picks = phase1["GARP screen"]

    # ====================================================================
    # Phase 2 — sequential (each depends on Phase 1 outputs)
    # ====================================================================
    _step("Building stock-in-focus…")
    from src.agent.stock_in_focus import build_focus  # local import to avoid circular
    sif = _safe(lambda: build_focus(qv_picks, garp_picks),
                "Stock-in-focus", errors, {})

    # Phase 3: forensic watch — run accounting-quality forensics on
    #   (a) top screen winners (catches "looks great on ratios, ugly under the hood")
    #   (b) today's biggest losers (where quality erosion is starting to price in)
    # Limited to ~25 names so the brief gathers in reasonable time.
    def _forensics():
        seeds = set()
        for p in qv_picks[:10]:
            if p.get("ticker"): seeds.add(p["ticker"].upper())
        for p in garp_picks[:10]:
            if p.get("ticker"): seeds.add(p["ticker"].upper())
        for l in movers.get("losers", [])[:10]:
            if l.get("symbol") or l.get("ticker"):
                seeds.add((l.get("symbol") or l.get("ticker")).upper())
        out = []
        for t in list(seeds)[:25]:
            try:
                r = forensic_analyze(t)
                if not r.fetched_ok or r.composite_score < 40:
                    continue
                # Top 2 red-flag notes per name keep prompt small
                red_notes = [m.note for m in r.metrics.values() if m.verdict == "red"][:2]
                out.append({
                    "ticker": r.ticker,
                    "score": r.composite_score,
                    "verdict": r.verdict,
                    "top_flags": red_notes,
                    "headline": r.headline_flag,
                })
            except Exception as exc:
                log.warning("forensic %s failed: %s", t, exc)
        out.sort(key=lambda x: -x["score"])
        return out[:5]

    _step("Running forensic watch…")
    forensic_watch = _safe(_forensics, "Forensic watch", errors, [])

    # ====================================================================
    # Phase 3 — enrich each pick with multi-signal conviction + brief-delta
    # ====================================================================
    _step("Enriching picks with conviction + delta…")
    today_iso = date.today().isoformat()

    # Build the "sets where this ticker fires" once, then check membership cheaply
    smart_money_set: set[str] = set()
    for d in deals_sum.get("institutional_buys", []) or []:
        sym = d.get("symbol") or d.get("ticker")
        if sym:
            smart_money_set.add(str(sym).upper())
    for d in insider_sum.get("promoter_buys", []) or []:
        sym = d.get("symbol") or d.get("ticker")
        if sym:
            smart_money_set.add(str(sym).upper())

    special_sit_set: set[str] = {
        (s.get("ticker") or s.get("symbol") or "").upper()
        for s in phase1["Special-sit"] or []
        if s.get("ticker") or s.get("symbol")
    }

    # Forensic verdict per ticker: re-use forensic_watch (red/amber names) +
    # default to "clean" for anyone we DIDN'T flag. forensic_watch only
    # surfaces composite ≥ 40, so absent-from-watch ≈ green/amber.
    forensic_concern: Dict[str, str] = {
        f["ticker"].upper(): f["verdict"]
        for f in forensic_watch if f.get("ticker")
    }

    # Reverse-DCF + momentum per pick — run in parallel since each is ~1s
    # warm. Targets the ~10-15 unique tickers across qv_picks + garp_picks.
    target_tickers = set()
    for p in (qv_picks or []) + (garp_picks or []):
        t = (p.get("ticker") or "").upper()
        if t:
            target_tickers.add(t)
    if sif and sif.get("ticker"):
        target_tickers.add(sif["ticker"].upper())

    from src.screens.reverse_dcf import analyze as _rdcf_analyze
    from src.data.prices import PricesAdapter as _Prices
    from src.screens.swing_setups import relative_strength_vs_index as _rs_vs_index

    _prices_inst = _Prices()
    _nifty = _safe(lambda: _prices_inst.history("^NSEI", period="200d"),
                   "RS Nifty", errors, None)
    _nifty_close = _nifty["Close"] if _nifty is not None and not _nifty.empty else None

    def _enrich_one(ticker: str) -> Dict[str, Any]:
        info: Dict[str, Any] = {"ticker": ticker}
        try:
            r = _rdcf_analyze(ticker)
            info["dcf_verdict"] = r.verdict if r.fetched_ok else None
        except Exception:
            info["dcf_verdict"] = None
        try:
            df = _prices_inst.history(f"{ticker}.NS", period="200d")
            if not df.empty and _nifty_close is not None:
                rs = _rs_vs_index(df["Close"], _nifty_close, 90)
                info["rs_90d"] = float(rs) if rs is not None else None
            else:
                info["rs_90d"] = None
        except Exception:
            info["rs_90d"] = None
        return info

    ticker_signals: Dict[str, Dict[str, Any]] = {}
    if target_tickers:
        with ThreadPoolExecutor(max_workers=max_workers) as ex2:
            futs = {ex2.submit(_enrich_one, t): t for t in target_tickers}
            for fut in as_completed(futs):
                ticker = futs[fut]
                try:
                    ticker_signals[ticker] = fut.result()
                except Exception as exc:
                    log.warning("conviction enrich %s failed: %s", ticker, exc)
                    ticker_signals[ticker] = {"ticker": ticker}

    # Brief history store — for delta_status + days_in_brief
    from src.data.brief_history import BriefHistoryStore
    history = BriefHistoryStore()

    # Cross-screen membership — surface ticker appearing in BOTH Q+V and GARP
    qv_tickers = {(p.get("ticker") or "").upper() for p in (qv_picks or [])}
    garp_tickers = {(p.get("ticker") or "").upper() for p in (garp_picks or [])}
    in_both_screens = (qv_tickers & garp_tickers) - {""}

    def _enrich_picks(picks: List[Dict[str, Any]], section: str) -> List[Dict[str, Any]]:
        for p in picks or []:
            ticker = (p.get("ticker") or "").upper()
            if not ticker:
                continue
            sigs: List[str] = [section]   # the screen the pick came from is signal #1
            if ticker in in_both_screens and section in ("qv", "garp"):
                # Independent confirm: another screen also surfaced this name
                other = "garp" if section == "qv" else "qv"
                sigs.append(f"{other}_also")
            if ticker in special_sit_set:
                sigs.append("special_sit")
            if ticker in smart_money_set:
                sigs.append("smart_money_buy")
            # forensic: clean unless flagged
            fv = forensic_concern.get(ticker)
            if fv is None:
                sigs.append("forensic_clean")
            elif fv == "amber":
                sigs.append("forensic_amber")
            # else red — DON'T add (skipping is the signal)
            ts = ticker_signals.get(ticker, {})
            if ts.get("dcf_verdict") == "cheap":
                sigs.append("dcf_cheap")
            rs = ts.get("rs_90d")
            if rs is not None and rs > 0:
                sigs.append("momentum_pos")
            p["conviction_signals"] = sigs
            p["conviction_count"] = len([s for s in sigs if s not in ("forensic_amber",)])

            # Delta from history
            try:
                d = history.delta_for_ticker(ticker, today=today_iso)
                p["delta_status"] = "new_today" if d.is_new else "persistent"
                p["days_in_brief"] = d.days_in_brief
            except Exception as exc:
                log.warning("delta lookup %s failed: %s", ticker, exc)
                p["delta_status"] = "unknown"
                p["days_in_brief"] = None
        return picks

    qv_picks = _enrich_picks(qv_picks, "qv")
    garp_picks = _enrich_picks(garp_picks, "garp")
    if sif and sif.get("ticker"):
        # Treat stock-in-focus as its own section for the history record
        _enrich_picks([sif], "focus")

    # Persist today's snapshot to history (will be queried tomorrow for delta).
    # Save BEFORE enrichment-time delta lookup wouldn't change anything because
    # delta_for_ticker looks at brief_history < today, not today.
    try:
        history.save_brief(today_iso, {
            "qv": qv_picks,
            "garp": garp_picks,
            "focus": [sif] if sif and sif.get("ticker") else [],
        })
    except Exception as exc:
        log.warning("brief history save failed: %s", exc)

    _step("✓ All data gathered")

    # All Phase 1 outputs come straight from the parallel dict — no re-running.
    return DailyNoteData(
        today=today,
        macro_fred=phase1["FRED"],
        macro_imf=phase1["IMF"],
        macro_wb=phase1["WorldBank"],
        indices_snapshot=phase1["Indices"],
        global_cues=phase1["Global cues"],
        fii_dii=phase1["FII/DII flows"],
        gainers=movers.get("gainers", []),
        losers=movers.get("losers", []),
        breadth={"advances": movers.get("advances", 0),
                 "declines": movers.get("declines", 0),
                 "unchanged": movers.get("unchanged", 0),
                 "adv_dec_ratio": movers.get("adv_dec_ratio")},
        top_quality_value=qv_picks,
        top_garp=garp_picks,
        swing_setups=phase1["Swing setups"],
        special_situations=phase1["Special-sit"],
        rbi_items=phase1["RBI"],
        sebi_items=phase1["SEBI"],
        theme_sentiment=phase1["GDELT themes"],
        block_deals=deals_sum.get("block_top", []),
        institutional_bulk_deals=deals_sum.get("institutional_buys", []),
        promoter_buys=insider_sum.get("promoter_buys", []),
        promoter_sells=insider_sum.get("promoter_sells", []),
        fno_signals=phase1["F&O signals"],
        econ_calendar=phase1["Econ calendar"],
        rebalance_predictions=phase1["Rebalance"],
        stock_in_focus=sif,
        forensic_watch=forensic_watch,
        errors=errors,
    )


# ============================================================
# Cache warm-up — runs gather() once in the background at container startup
# so the first user click hits warm SQLite caches across all adapters.
# Idempotent + non-blocking. Safe to import at app entry.
# ============================================================

_warmup_started = False
_warmup_lock = threading.Lock()


def start_warmup() -> None:
    """Kick off a one-shot background warm-up of the gather() pipeline.

    Idempotent — calling twice is a no-op. Failures are swallowed (we want
    a clean web start regardless of upstream outages). The point is to
    populate the SQLite adapter caches so the first user request to
    Daily Morning Brief is fast.
    """
    global _warmup_started
    with _warmup_lock:
        if _warmup_started:
            return
        _warmup_started = True

    def _bg():
        try:
            log.info("daily_note warm-up: starting background gather()…")
            gather()
            log.info("daily_note warm-up: complete.")
        except Exception as exc:
            log.warning("daily_note warm-up failed (non-fatal): %s", exc)

    t = threading.Thread(target=_bg, name="daily-note-warmup", daemon=True)
    t.start()


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
            "",
            "## Forensic Watch — earnings-quality red flags (composite ≥ 40)",
            "Names from screen winners or today's losers that flunk the accounting-quality "
            "battery (CFO/PAT, Sloan accruals, working-capital drift, debt-vs-profit "
            "divergence, Beneish components). Surface 1-2 of these in **Risk Watch** with the "
            "specific red flag — these are 'the financials look fine on ratios, but here's "
            "what to check before the next results print' calls.",
            "```json", json.dumps(d.forensic_watch, indent=2, default=str), "```",
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
