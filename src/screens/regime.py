"""Macro regime detector + relative-strength engine.

Two things in one module:

  1. RegimeReport — a composite 0-100 "risk-on-ness" score for the Indian
     equity market, built from observable inputs:
        - Nifty position vs 50DMA + 200DMA
        - FII / DII net flow trend (last 5 sessions)
        - Sectoral breadth (% of 10 sectoral indices trading above own 50DMA)
        - USD/INR direction (weakening rupee = risk-off for India equity)
        - Brent crude trend (rising = risk-off for India)
     Final label: risk_on | neutral | risk_off

  2. relative_strength_table — per-ticker RS vs Nifty across 1M / 3M / 6M /
     12M windows. The fundamental rotation read: which names are *leading*
     vs the index, and which are lagging.

Methodology is intentionally simple — readers can audit every number.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.data.flows import FlowsAdapter
from src.data.prices import INDIAN_INDICES, PricesAdapter

log = logging.getLogger(__name__)


# Component weights for the composite regime score (sum to 1.0)
REGIME_WEIGHTS: Dict[str, float] = {
    "nifty_trend":     0.30,
    "flows":           0.20,
    "sector_breadth":  0.20,
    "inr":             0.15,
    "brent":           0.15,
}

WINDOW_DAYS = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}


@dataclass
class RegimeReport:
    composite_score: float           # 0-100, higher = more risk-on
    label: str                       # "risk_on" | "neutral" | "risk_off"
    components: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    fetched_ok: bool = True


# ============================================================
# Component scorers — each returns a 0-100 score
# ============================================================

def _score_nifty_trend(close: pd.Series) -> Tuple[float, str]:
    if close is None or close.empty:
        return 50.0, "insufficient Nifty history → neutral"
    clean = close.dropna()
    if len(clean) < 200:
        return 50.0, "insufficient Nifty history → neutral"
    latest = float(clean.iloc[-1])
    sma50 = float(clean.rolling(50).mean().iloc[-1])
    sma200 = float(clean.rolling(200).mean().iloc[-1])
    above_50 = latest > sma50
    above_200 = latest > sma200
    gap_50 = (latest / sma50 - 1) * 100
    gap_200 = (latest / sma200 - 1) * 100

    # Score: 100 above both with strong gap; 0 below both with weak gap
    if above_50 and above_200:
        score = 60 + min(max(gap_50, 0), 5) * 4 + min(max(gap_200, 0), 5) * 4   # cap at 100
        score = min(100, score)
    elif above_200 and not above_50:
        score = 50   # bullish long-term but pulling back short-term
    elif above_50 and not above_200:
        score = 40   # short-term bounce in larger downtrend
    else:
        score = 20 + min(max(gap_50 + gap_200, -10), 0)   # both below, deeply
    note = (f"Nifty {gap_50:+.1f}% vs 50DMA, {gap_200:+.1f}% vs 200DMA "
            f"({'above' if above_200 else 'below'} long-term trend)")
    return float(max(0, min(100, score))), note


def _score_flows(flows_rows: List[Dict]) -> Tuple[float, str]:
    """FII + DII net buys last 5 sessions. Positive total = risk-on bias."""
    if not flows_rows:
        return 50.0, "flows unavailable"
    # latest fii_dii_latest is descending — take last 5
    rows = flows_rows[:5]
    fii_total = sum((r.get("fii_net_cr") or 0) for r in rows)
    dii_total = sum((r.get("dii_net_cr") or 0) for r in rows)
    combined = fii_total + dii_total
    # Scaling: ±20,000 Cr over 5 days is "extreme" — anchor 100 at +20k, 0 at -20k
    score = 50 + min(max(combined / 200, -50), 50)
    note = (f"5d FII net ₹{fii_total:+,.0f} Cr + DII net ₹{dii_total:+,.0f} Cr = "
            f"₹{combined:+,.0f} Cr combined")
    return float(max(0, min(100, score))), note


def _score_sector_breadth(prices: PricesAdapter) -> Tuple[float, str]:
    """% of Indian sectoral indices trading above own 50DMA."""
    sectors = [(n, s) for n, s in INDIAN_INDICES.items()
               if s.startswith("^CNX") or s in ("^NSEBANK",)]
    above = 0
    counted = 0
    for name, sym in sectors:
        try:
            df = prices.history(sym, period="200d")
            if df.empty or len(df) < 50:
                continue
            close = df["Close"]
            if float(close.iloc[-1]) > float(close.rolling(50).mean().iloc[-1]):
                above += 1
            counted += 1
        except Exception:
            continue
    if counted == 0:
        return 50.0, "sector data unavailable"
    pct = above / counted * 100
    note = f"{above}/{counted} sector indices above own 50DMA ({pct:.0f}%)"
    return float(pct), note


def _score_inr(close: Optional[pd.Series]) -> Tuple[float, str]:
    """USDINR rising = INR weakening = risk-off for Indian equity (FII outflow,
    import inflation, multinationals translation hit)."""
    if close is None or close.empty:
        return 50.0, "USDINR unavailable"
    clean = close.dropna()
    if len(clean) < 60:
        return 50.0, "USDINR insufficient history"
    latest = float(clean.iloc[-1])
    sma50 = float(clean.rolling(50).mean().iloc[-1])
    gap = (latest / sma50 - 1) * 100
    score = 50 - gap * 25
    direction = "INR weakening (risk-off)" if gap > 0 else "INR strengthening (risk-on)"
    note = f"USDINR {gap:+.2f}% vs 50DMA — {direction}"
    return float(max(0, min(100, score))), note


def _score_brent(close: Optional[pd.Series]) -> Tuple[float, str]:
    """Brent rising = oil-import-heavy India risk-off; falling = risk-on."""
    if close is None or close.empty:
        return 50.0, "Brent unavailable"
    clean = close.dropna()
    if len(clean) < 60:
        return 50.0, "Brent insufficient history"
    latest = float(clean.iloc[-1])
    sma50 = float(clean.rolling(50).mean().iloc[-1])
    gap = (latest / sma50 - 1) * 100
    score = 50 - gap * 4
    direction = "oil rising (risk-off)" if gap > 0 else "oil falling (risk-on)"
    note = f"Brent {gap:+.2f}% vs 50DMA — {direction}"
    return float(max(0, min(100, score))), note


# ============================================================
# Public API
# ============================================================

def regime_report(prices: Optional[PricesAdapter] = None) -> RegimeReport:
    prices = prices or PricesAdapter()
    components: Dict[str, float] = {}
    notes: List[str] = []

    # Nifty trend
    try:
        nifty = prices.history("^NSEI", period="400d")
        s, n = _score_nifty_trend(nifty["Close"] if not nifty.empty else None)
    except Exception as exc:
        s, n = 50.0, f"Nifty fetch failed: {exc}"
    components["nifty_trend"] = s; notes.append(n)

    # Flows
    try:
        rows = FlowsAdapter().fii_dii_latest()
        s, n = _score_flows(rows)
    except Exception as exc:
        s, n = 50.0, f"flows fetch failed: {exc}"
    components["flows"] = s; notes.append(n)

    # Sector breadth
    try:
        s, n = _score_sector_breadth(prices)
    except Exception as exc:
        s, n = 50.0, f"sector breadth failed: {exc}"
    components["sector_breadth"] = s; notes.append(n)

    # USDINR
    try:
        inr = prices.history("INR=X", period="200d")
        s, n = _score_inr(inr["Close"] if not inr.empty else None)
    except Exception as exc:
        s, n = 50.0, f"USDINR fetch failed: {exc}"
    components["inr"] = s; notes.append(n)

    # Brent
    try:
        br = prices.history("BZ=F", period="200d")
        s, n = _score_brent(br["Close"] if not br.empty else None)
    except Exception as exc:
        s, n = 50.0, f"Brent fetch failed: {exc}"
    components["brent"] = s; notes.append(n)

    composite = sum(components[k] * REGIME_WEIGHTS[k] for k in REGIME_WEIGHTS)
    label = ("risk_on" if composite >= 60
             else ("risk_off" if composite <= 40 else "neutral"))

    return RegimeReport(
        composite_score=round(composite, 1),
        label=label,
        components=components,
        notes=notes,
        fetched_ok=True,
    )


def relative_strength_table(universe: List[str],
                            prices: Optional[PricesAdapter] = None) -> pd.DataFrame:
    """For each ticker, RS vs Nifty across 1M / 3M / 6M / 12M windows.
    RS_n = (ticker_n_day_return - nifty_n_day_return) in pct points.

    Returns DataFrame indexed by ticker, columns = ['RS_1M','RS_3M','RS_6M','RS_12M'].
    """
    prices = prices or PricesAdapter()
    nifty = prices.history("^NSEI", period="400d")
    if nifty.empty:
        return pd.DataFrame()
    nifty_close = nifty["Close"]

    def _pct_return(series: pd.Series, days: int) -> Optional[float]:
        """%-return over `days` trading days, robust to NaN tail bars from yfinance."""
        if series is None or series.empty:
            return None
        clean = series.dropna()
        if len(clean) < days + 1:
            return None
        return float((clean.iloc[-1] / clean.iloc[-days - 1] - 1) * 100)

    rows = []
    for t in universe:
        try:
            df = prices.history(f"{t.upper()}.NS", period="400d")
            if df.empty or len(df) < 30:
                continue
            close = df["Close"]
            row = {"ticker": t.upper()}
            for label, days in WINDOW_DAYS.items():
                ticker_ret = _pct_return(close, days)
                nifty_ret = _pct_return(nifty_close, days)
                row[f"RS_{label}"] = (round(ticker_ret - nifty_ret, 2)
                                      if ticker_ret is not None and nifty_ret is not None
                                      else None)
            rows.append(row)
        except Exception as exc:
            log.debug("RS fetch %s failed: %s", t, exc)
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("ticker")
    return df.sort_values("RS_3M", ascending=False, na_position="last")
