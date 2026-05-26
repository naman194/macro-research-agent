"""Cross-sectional joint screen — names where multiple independent signals agree.

The 'data-backed' principle: a single signal is noise; agreement across
independent signals is information. This screen counts how many of the
following are simultaneously true for each ticker:

  1. Q+V       — passes Quality+Value hard filters
  2. GARP      — passes GARP filters
  3. Forensic  — earnings-quality composite is GREEN (< 30)
  4. DCF       — reverse-DCF verdict is 'cheap' (market under-pricing growth)
  5. Smart $   — appears in last 30-day promoter buys OR institutional bulk buys
  6. Momentum  — 90-day relative strength vs Nifty is positive

Output: every ticker with its alignment score (0-6), the signals that fired,
and which ones it failed. Surface names hitting 3+ as the high-conviction set.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import pandas as pd

from src.data.deals import DealsAdapter
from src.data.insider import InsiderAdapter
from src.data.prices import PricesAdapter
from src.screens.forensics import ForensicsScreener
from src.screens.garp import GARPScreener
from src.screens.quality_value import QualityValueScreener
from src.screens.reverse_dcf import ReverseDCFScreener
from src.screens.swing_setups import relative_strength_vs_index

log = logging.getLogger(__name__)


SIGNAL_LABELS = {
    "qv":       "Q+V (Buffett-style)",
    "garp":     "GARP",
    "forensic": "Forensic green",
    "dcf":      "Reverse-DCF cheap",
    "smart":    "Smart-money buying",
    "momentum": "90d momentum positive",
}


@dataclass
class JointResult:
    universe_size: int
    candidates: pd.DataFrame                  # ticker, alignment_score, plus per-signal flags
    signals_descriptions: Dict[str, str] = field(default_factory=dict)
    diagnostics: Dict[str, int] = field(default_factory=dict)


def _smart_money_tickers(days_back: int = 30) -> Set[str]:
    """Union of promoter-buy and institutional-bulk-buy tickers in the last N days."""
    out: Set[str] = set()
    try:
        deals = DealsAdapter().latest_summary(top_n=50)
        for d in deals.get("institutional_buys", []):
            sym = d.get("symbol") or d.get("ticker")
            if sym:
                out.add(str(sym).upper())
    except Exception as exc:
        log.warning("smart-money deals fetch failed: %s", exc)
    try:
        insider = InsiderAdapter().latest_summary(days_back=days_back, top_n=50)
        for d in insider.get("promoter_buys", []):
            sym = d.get("symbol") or d.get("ticker")
            if sym:
                out.add(str(sym).upper())
    except Exception as exc:
        log.warning("smart-money insider fetch failed: %s", exc)
    return out


def _momentum_set(universe: List[str], prices: Optional[PricesAdapter] = None,
                  min_rs_pct: float = 0.0) -> Set[str]:
    """Tickers with 90d RS > min_rs_pct vs Nifty. Yfinance hits per ticker —
    cached at the adapter level via SQLite."""
    prices = prices or PricesAdapter()
    nifty = prices.history("^NSEI", period="200d")
    if nifty.empty:
        return set()
    nifty_close = nifty["Close"]

    out: Set[str] = set()
    for t in universe:
        try:
            df = prices.history(f"{t}.NS", period="200d")
            if df.empty or len(df) < 100:
                continue
            rs = relative_strength_vs_index(df["Close"], nifty_close, 90)
            if rs is not None and rs > min_rs_pct:
                out.add(t.upper())
        except Exception:
            continue
    return out


def run_joint_screen(universe: List[str],
                     min_alignment: int = 2,
                     require_macro_uptrend: bool = False) -> JointResult:
    """Run the joint screen across a universe. Returns every ticker with its
    alignment score and per-signal pass/fail, sorted by alignment desc."""
    universe = [t.upper() for t in universe]
    diag: Dict[str, int] = {}

    # ---- run each underlying screen, collect the *tickers that pass* per signal
    qv = QualityValueScreener().run(universe)
    qv_pass = set(qv.candidates["ticker"].str.upper()) if not qv.candidates.empty else set()
    diag["qv_pass"] = len(qv_pass)

    garp = GARPScreener().run(universe)
    garp_pass = set(garp.candidates["ticker"].str.upper()) if not garp.candidates.empty else set()
    diag["garp_pass"] = len(garp_pass)

    forensic = ForensicsScreener().run(universe)
    forensic_green = set()
    if not forensic.candidates.empty:
        df = forensic.candidates
        forensic_green = set(df[df["verdict"] == "green"]["ticker"].str.upper())
    diag["forensic_green"] = len(forensic_green)

    rdcf = ReverseDCFScreener().run(universe)
    dcf_cheap = set()
    if not rdcf.candidates.empty:
        df = rdcf.candidates
        dcf_cheap = set(df[df["verdict"] == "cheap"]["ticker"].str.upper())
    diag["dcf_cheap"] = len(dcf_cheap)

    smart = _smart_money_tickers()
    diag["smart_money_universe"] = len(smart)

    momentum = _momentum_set(universe)
    diag["momentum_positive"] = len(momentum)

    # ---- build per-ticker alignment
    rows = []
    for t in universe:
        flags = {
            "qv":       t in qv_pass,
            "garp":     t in garp_pass,
            "forensic": t in forensic_green,
            "dcf":      t in dcf_cheap,
            "smart":    t in smart,
            "momentum": t in momentum,
        }
        score = sum(1 for v in flags.values() if v)
        if score < min_alignment:
            continue
        rows.append({
            "ticker": t,
            "alignment_score": score,
            "signals_firing": ", ".join(k for k, v in flags.items() if v),
            "signals_missing": ", ".join(k for k, v in flags.items() if not v),
            **{f"sig_{k}": v for k, v in flags.items()},
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["alignment_score", "ticker"],
                            ascending=[False, True]).reset_index(drop=True)
    return JointResult(
        universe_size=len(universe),
        candidates=df,
        signals_descriptions=SIGNAL_LABELS,
        diagnostics=diag,
    )
