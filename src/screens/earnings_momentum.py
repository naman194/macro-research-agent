"""Earnings momentum — delivered EPS trajectory across the universe.

What this is: a free-data proxy for the *single* most predictive signal in
equities — sell-side EPS estimate revisions. We don't have consensus revisions
without a paid feed (Refinitiv / Bloomberg), so we compute the closest analog:
trailing-twelve-month EPS *delivered* across the last 8 quarters, and whether
that TTM is *accelerating*.

Why this works as a proxy:
- Consensus follows delivery. When a company beats and raises, analysts
  upgrade. Tracking the delivery directly gets you the same signal with
  zero lag and zero data cost.
- TTM smooths quarterly seasonality (Q3 vs Q4 distortions in Indian retail,
  Q1 vs Q4 in industrials).
- Comparing rolling-4Q sums in pairs catches acceleration: if EPS grew 10% YoY
  last quarter but only 4% YoY three quarters ago, the trend is *speeding up*.

Verdicts (per ticker):
  accelerating   — TTM EPS growth rising and positive (best signal)
  steady_growth  — positive growth, stable pace (5-25% range)
  stable         — flat (-5% to +5%) — value name, not momentum
  decelerating   — positive but slowing
  declining      — TTM EPS shrinking
  na             — insufficient quarterly history
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from src.data.screener import ScreenerAdapter
from src.screens.base import Screener, ScreenResult

log = logging.getLogger(__name__)


@dataclass
class EarningsMomentumReport:
    ticker: str
    ttm_eps_latest: Optional[float] = None
    ttm_eps_prior: Optional[float] = None    # TTM ending 4 quarters ago
    ttm_yoy_growth_pct: Optional[float] = None
    early_ttm_yoy_pct: Optional[float] = None  # comparison window 4 quarters older
    acceleration_pct: Optional[float] = None    # ttm_yoy - early_ttm_yoy
    verdict: str = "na"
    note: str = ""
    fetched_ok: bool = True


def _ttm_sum(values: List[float], end_index: int) -> Optional[float]:
    """Sum 4 quarters ending at end_index (inclusive). end_index is from the
    END of the list (so -1 = latest)."""
    if not values or end_index >= 0 or end_index < -len(values):
        return None
    start = end_index - 3
    if -start > len(values):
        return None
    window = values[start:end_index + 1] if end_index < -1 else values[start:]
    if len(window) < 4 or any(v is None for v in window):
        return None
    return sum(window)


def analyze(ticker: str, adapter: Optional[ScreenerAdapter] = None) -> EarningsMomentumReport:
    adapter = adapter or ScreenerAdapter()
    try:
        qr = adapter.quarterly_results(ticker)
    except Exception as exc:
        log.warning("earnings momentum %s: %s", ticker, exc)
        return EarningsMomentumReport(ticker=ticker, fetched_ok=False,
                                      note=f"fetch failed: {exc}")

    if qr.get("error"):
        return EarningsMomentumReport(ticker=ticker, fetched_ok=False,
                                      note=qr["error"])

    metrics = qr.get("metrics") or {}
    eps_row = metrics.get("EPS in Rs")
    if not eps_row or len(eps_row) < 8:
        return EarningsMomentumReport(ticker=ticker, fetched_ok=True,
                                      note=f"need 8+ quarters of EPS, got {len(eps_row) if eps_row else 0}")

    # Clean None / NaN; need at least 8 valid quarters
    eps = [float(v) if v is not None and not (isinstance(v, float) and v != v) else None
           for v in eps_row]
    if sum(1 for v in eps if v is not None) < 8:
        return EarningsMomentumReport(ticker=ticker, fetched_ok=True,
                                      note="too many NaN quarters in EPS row")

    # TTM windows: latest 4Q, prior 4Q (ending 4 quarters back),
    #              early 4Q (ending 8 quarters back) — gives us 2 YoY comparisons
    if len(eps) < 8:
        return EarningsMomentumReport(ticker=ticker, fetched_ok=True,
                                      note="<8 quarters")
    ttm_latest = _ttm_sum(eps, -1)
    ttm_prior  = _ttm_sum(eps, -5) if len(eps) >= 8 else None
    ttm_early  = _ttm_sum(eps, -9) if len(eps) >= 12 else None

    if ttm_latest is None or ttm_prior is None or ttm_prior <= 0:
        return EarningsMomentumReport(ticker=ticker, fetched_ok=True,
                                      note="TTM sums incomputable (None or non-positive prior)")

    ttm_yoy = (ttm_latest / ttm_prior - 1) * 100

    early_ttm_yoy = None
    if ttm_early is not None and ttm_early > 0:
        # Hypothetical: TTM ending 4Q back vs TTM ending 8Q back
        early_ttm_yoy = (ttm_prior / ttm_early - 1) * 100

    accel = None
    if early_ttm_yoy is not None:
        accel = ttm_yoy - early_ttm_yoy

    # Verdict
    if ttm_yoy < -5:
        verdict = "declining"
    elif -5 <= ttm_yoy <= 5:
        verdict = "stable"
    elif accel is not None and accel > 5 and ttm_yoy > 10:
        verdict = "accelerating"
    elif accel is not None and accel < -5 and ttm_yoy > 5:
        verdict = "decelerating"
    elif 5 < ttm_yoy <= 25:
        verdict = "steady_growth"
    else:
        verdict = "steady_growth"

    note = (f"TTM EPS ₹{ttm_latest:.1f} vs ₹{ttm_prior:.1f} 4Q ago = "
            f"{ttm_yoy:+.1f}% YoY")
    if accel is not None:
        note += f" (vs {early_ttm_yoy:+.1f}% the year before — accel {accel:+.1f}pp)"

    return EarningsMomentumReport(
        ticker=ticker,
        ttm_eps_latest=round(ttm_latest, 2),
        ttm_eps_prior=round(ttm_prior, 2),
        ttm_yoy_growth_pct=round(ttm_yoy, 1),
        early_ttm_yoy_pct=round(early_ttm_yoy, 1) if early_ttm_yoy is not None else None,
        acceleration_pct=round(accel, 1) if accel is not None else None,
        verdict=verdict,
        note=note,
        fetched_ok=True,
    )


class EarningsMomentumScreener(Screener):
    framework = "earnings_momentum"

    def __init__(self, adapter: Optional[ScreenerAdapter] = None):
        self.adapter = adapter or ScreenerAdapter()

    def run(self, universe: List[str]) -> ScreenResult:
        rows = []
        rejected = 0
        for t in universe:
            r = analyze(t, self.adapter)
            if not r.fetched_ok:
                rejected += 1
                continue
            rows.append({
                "ticker": r.ticker,
                "verdict": r.verdict,
                "ttm_yoy_pct": r.ttm_yoy_growth_pct,
                "early_ttm_yoy_pct": r.early_ttm_yoy_pct,
                "acceleration_pp": r.acceleration_pct,
                "ttm_eps_latest": r.ttm_eps_latest,
                "ttm_eps_prior": r.ttm_eps_prior,
                "note": r.note,
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("ttm_yoy_pct", ascending=False, na_position="last") \
                   .reset_index(drop=True)

        return ScreenResult(
            framework=self.framework,
            candidates=df,
            rejected_count=rejected,
            notes=[
                "TTM EPS = sum of last 4 quarterly EPS. Smooths seasonal distortion.",
                "YoY growth: latest TTM vs TTM ending 4 quarters ago.",
                "Acceleration: latest TTM-YoY minus the prior-year's TTM-YoY (in pp).",
                "**accelerating** is the strongest signal — growth that's speeding up.",
                "**declining** TTM EPS often precedes downgrade cycles in Indian midcaps.",
            ],
            criteria={
                "min_quarters_required": "8 quarters of EPS (2 full TTM windows)",
                "acceleration_threshold_pp": "5 (to flag accelerating)",
                "data_source": "screener.in Quarterly Results — EPS in Rs row",
            },
        )
