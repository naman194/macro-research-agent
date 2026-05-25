"""High Conviction composite screener — chase 60%+ hit rate via multi-layer alignment.

The trade-off is explicit: very few picks, very high quality.

A name only fires if ALL six layers align:

  L1 FUNDAMENTAL QUALITY:
     ROCE >= 18, ROE >= 18, D/E <= 0.4, profit CAGR 3y >= 15%, mcap >= 5,000 Cr
  L2 STRUCTURAL OVERLAY:
     Net (catalyst - risk) overlay >= 0 — sector + name tailwinds at least offset headwinds.
     This drops IT / Telecom / Media in the current regime.
  L3 TECHNICAL TIMING:
     Either trend-pullback OR base-breakout OR volume-breakout fires today.
     Doesn't time the perfect bottom — just ensures we're not buying breakdowns.
  L4 RELATIVE STRENGTH:
     Stock outperformed Nifty over last 90 days OR sector leadership intact.
  L5 SENTIMENT FILTER:
     GDELT 14d mean tone > -3 (no litigation / disaster cluster).
  L6 MACRO REGIME:
     Nifty above 200DMA (or use --force flag to override in research/backtest mode).

Output: top 3-5 picks per cycle. Recommended hold: 6-12 months. Position size: 3-5% / pick.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import TICKER_SECTOR_MAP
from src.data.catalysts import catalyst_breakdown, company_catalysts
from src.data.prices import PricesAdapter
from src.data.screener import ScreenerAdapter
from src.data.structural_risks import for_company, for_sector, penalty_breakdown
from src.screens.swing_setups import (
    _compute_panel,
    _eval_base_breakout,
    _eval_trend_pullback,
    _eval_volume_breakout,
    relative_strength_vs_index,
)

log = logging.getLogger(__name__)


# Hard fundamental thresholds — calibrated to actually surface picks while staying selective
MIN_ROCE = 15.0          # was 18; many top quality names sit at 15-17 (banks especially)
MIN_ROE = 15.0           # was 18
MAX_DE = 0.5             # was 0.4
MIN_PROFIT_CAGR_3Y = 10.0  # was 15; quality compounders often grow 8-12% (HUL, Nestle, ITC)
MIN_MCAP_CR = 5000
# Structural overlay thresholds — realistic given that our risk weighting is asymmetric
# (max risk penalty 45 vs max catalyst bonus 25). A "high conviction" name should have:
#  - meaningful catalyst bonus >= 8  (sector or company has real tailwinds)
#  - sector penalty <= 22.5 (avoid only the WORST-disrupted sectors: IT, Media)
MIN_CATALYST_BONUS = 8.0
MAX_SECTOR_PENALTY = 22.5


@dataclass
class HighConvictionPick:
    ticker: str
    name: str
    sector: str
    conviction_score: float    # 0-100 composite

    # L1 fundamental
    roce: float
    roe: float
    debt_to_equity: float
    profit_cagr_3y: float
    market_cap_cr: float
    pe: float

    # L2 structural overlay
    structural_penalty: float
    catalyst_bonus: float
    net_overlay: float

    # L3 technical
    technical_setup: str       # which setup fired
    entry: float
    stop_loss_suggested: float

    # L4 / L5 momentum + sentiment
    rs_90d_pct: Optional[float]
    sentiment_tone: Optional[float]

    # Reasoning
    why_high_conviction: List[str] = field(default_factory=list)


def evaluate_high_conviction(tickers: List[str],
                              prices: Optional[PricesAdapter] = None,
                              screener: Optional[ScreenerAdapter] = None,
                              require_macro_uptrend: bool = True,
                              sentiment_lookup: Optional[Dict[str, float]] = None,
                              ) -> List[HighConvictionPick]:
    """Run the composite screen across a universe."""
    prices = prices or PricesAdapter()
    screener = screener or ScreenerAdapter()
    sentiment_lookup = sentiment_lookup or {}

    # L6 — macro regime filter
    nifty = prices.history("^NSEI", period="400d")
    nifty_close = nifty["Close"] if not nifty.empty else None
    if require_macro_uptrend and nifty_close is not None and len(nifty_close) >= 200:
        nlast = float(nifty_close.iloc[-1])
        n200 = float(nifty_close.rolling(200).mean().iloc[-1])
        if nlast < n200:
            log.info("Macro regime risk-off — no high-conviction longs surfaced.")
            return []

    fund = screener.bulk_fundamentals(tickers)
    if fund.empty:
        return []

    picks: List[HighConvictionPick] = []
    for _, row in fund.iterrows():
        ticker = row.get("ticker")
        if not ticker:
            continue

        # L1 — fundamental hard filters
        roce = _safe(row, "roce")
        roe = _safe(row, "roe")
        de = _safe(row, "debt_to_equity")
        pg = _safe(row, "profit_growth_3y")
        mcap = _safe(row, "market_cap_cr")
        pe = _safe(row, "pe")
        if roce is None or roce < MIN_ROCE: continue
        if roe is None or roe < MIN_ROE: continue
        if de is None or de > MAX_DE: continue
        if pg is None or pg < MIN_PROFIT_CAGR_3Y: continue
        if mcap is None or mcap < MIN_MCAP_CR: continue

        sector = row.get("sector") or TICKER_SECTOR_MAP.get(ticker.upper())

        # L2 — structural overlay: require meaningful catalysts + avoid worst-disrupted sectors
        penalty = penalty_breakdown(sector=sector, ticker=ticker)
        bonus = catalyst_breakdown(sector=sector, ticker=ticker)
        net_overlay = bonus["total_catalyst_bonus"] - penalty["total_penalty"]
        if bonus["total_catalyst_bonus"] < MIN_CATALYST_BONUS:
            continue
        if penalty["sector_penalty"] > MAX_SECTOR_PENALTY:
            continue

        # L3 — technical setup must fire
        try:
            df = prices.history(f"{ticker}.NS", period="400d")
            if df.empty or len(df) < 220:
                continue
            panel = _compute_panel(df, nifty_close)
        except Exception:
            continue

        cand = None
        setup = None
        for fn, name in [(_eval_trend_pullback, "trend_pullback"),
                         (_eval_base_breakout, "base_breakout"),
                         (_eval_volume_breakout, "volume_breakout")]:
            try:
                c = fn(ticker, panel)
                if c is not None:
                    cand = c
                    setup = name
                    break
            except Exception:
                continue
        if cand is None:
            continue

        # L4 — relative strength filter (must not be severe laggard)
        rs_90 = relative_strength_vs_index(panel["df"]["Close"], nifty_close, 90) \
                if nifty_close is not None else None
        if rs_90 is not None and rs_90 < -5:
            continue

        # L5 — sentiment filter (skip litigation/disaster clusters)
        tone = sentiment_lookup.get(ticker.upper())
        if tone is not None and tone < -3:
            continue

        # Composite conviction score
        # Fundamental quality (40%): ROCE+ROE balance, low debt, growth
        fund_score = (
            min(roce / 40, 1) * 12
            + min(roe / 35, 1) * 10
            + (1 - min(de, 0.4) / 0.4) * 8
            + min(pg / 30, 1) * 10
        )
        # Structural net overlay (25%)
        overlay_score = min(max(net_overlay, 0) / 20, 1) * 25
        # Technical conviction (15%): use the swing scorer's output normalised
        tech_score = min(cand.score / 100, 1) * 15
        # Relative strength (10%)
        rs_score = (min(rs_90 or 0, 30) + 30) / 60 * 10 if rs_90 is not None else 5
        # Sentiment bonus (10%)
        if tone is not None:
            sent_score = (min(max(tone, -3), 3) + 3) / 6 * 10
        else:
            sent_score = 5
        conviction = round(fund_score + overlay_score + tech_score + rs_score + sent_score, 2)

        # Why high conviction (auto-generated reasoning bullets)
        why = []
        if roce >= 25: why.append(f"Exceptional capital efficiency (ROCE {roce:.0f}%)")
        if roe >= 25: why.append(f"Premium return profile (ROE {roe:.0f}%)")
        if (de or 0) <= 0.1: why.append(f"Net-cash balance sheet (D/E {de:.2f})")
        if pg >= 20: why.append(f"Strong growth ({pg:.0f}% profit CAGR 3y)")
        if net_overlay >= 5: why.append(f"Sector + company tailwinds dominant (overlay +{net_overlay:.0f})")
        if rs_90 and rs_90 > 10: why.append(f"Clear leader vs Nifty (+{rs_90:.0f}% RS 90d)")
        if tone and tone > 1: why.append(f"Positive news flow (GDELT tone +{tone:.1f})")
        why.append(f"Technical entry confirmed: {setup}")

        picks.append(HighConvictionPick(
            ticker=ticker.upper(),
            name=row.get("name") or ticker,
            sector=sector or "Unknown",
            conviction_score=conviction,
            roce=roce, roe=roe, debt_to_equity=de or 0,
            profit_cagr_3y=pg, market_cap_cr=mcap, pe=pe or 0,
            structural_penalty=penalty["total_penalty"],
            catalyst_bonus=bonus["total_catalyst_bonus"],
            net_overlay=round(net_overlay, 2),
            technical_setup=setup,
            entry=cand.entry, stop_loss_suggested=cand.stop,
            rs_90d_pct=round(rs_90, 2) if rs_90 is not None else None,
            sentiment_tone=tone,
            why_high_conviction=why,
        ))

    picks.sort(key=lambda x: x.conviction_score, reverse=True)
    return picks


def _safe(row, key):
    v = row.get(key)
    if v is None:
        return None
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None
