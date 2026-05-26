"""Reverse-DCF — solve for the FCF growth rate implied by current price.

What this does that a P/E screen doesn't:
  Instead of asking "is this cheap?" it asks "what does the market believe
  about long-term FCF growth?" — then compares that to historical reality
  and a defensible sector ceiling. Names where market-implied < 5y historical
  growth are *potentially* cheap; names where implied > 2× historical are
  priced for perfection.

Model: two-stage DCF.
  Stage 1: 10y explicit at growth rate g (the unknown, solved for)
  Stage 2: terminal at g_t (default 4.5% — long-run India nominal GDP proxy)

  EV = Σ_{t=1..10} FCF_0·(1+g)^t / (1+WACC)^t
       + [FCF_0·(1+g)^10·(1+g_t) / (WACC − g_t)] / (1+WACC)^10

Solved by bisection (NPV is monotonic in g).

Inputs per ticker:
  FCF_0:   3-year average of screener.in's "Free Cash Flow" row, in Cr
  EV:      market cap + total borrowings (cash not netted — conservative; the
           screener.in annual BS doesn't break cash out cleanly. Net-of-cash
           is a Phase B refinement when an ROC adapter ships.)
  WACC:    sector prior; see SECTOR_WACC. Override per ticker in scenarios.
  g_t:     terminal growth, 4.5% default.

Interpretation:
  - implied growth < 5y historical sales CAGR → potentially cheap (market less
    optimistic than the business has demonstrated)
  - implied growth > sector ceiling (15-18% depending on sector) → priced for
    perfection
  - implied growth negative → market expecting decline; check whether the
    business is cyclical / in structural drawdown

Caveats:
  - Cyclical names (metals, autos, commodities) need normalised FCF, not
    point-in-time. The 3y average partly handles this.
  - Asset-heavy capex cycles distort FCF in build-out years. Flag with
    elevated capex/sales over the window.
  - Financials (banks, NBFCs, insurers) don't fit FCF-DCF; use embedded value
    or P/BV — skip in this screen.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import TICKER_SECTOR_MAP
from src.data.screener import ScreenerAdapter
from src.data.screener_premium import ScreenerPremiumAdapter
from src.screens.base import Screener, ScreenResult

log = logging.getLogger(__name__)


# =========================================================================
# Sector priors — Indian context
# Sources: cross-checked against analyst-consensus WACCs from sell-side
# India reports (Kotak / ICICI / JM) Apr-2026 average. Update if RBI repo
# rate makes a sustained > 100 bps move.
# =========================================================================

SECTOR_WACC: Dict[str, float] = {
    "IT": 0.110,
    "Consumer / FMCG": 0.100,
    "Pharma": 0.115,
    "Auto": 0.120,
    "Industrials / Capital Goods": 0.125,
    "Metals & Mining": 0.130,
    "Cement": 0.120,
    "Chemicals / Specialty": 0.120,
    "Power / Utilities": 0.100,
    "Realty": 0.135,
    "Telecom": 0.110,
    "Oil & Gas": 0.115,
    "Retail / QSR": 0.115,
    "Media": 0.125,
    "Default": 0.120,
}

# Sector growth ceiling — what we'd call "priced for perfection" if exceeded.
# A 10-year explicit-stage growth above this rate has rarely been delivered
# by Indian companies of meaningful size; ANY screen result above it
# warrants an explicit "what makes this name different" question.
SECTOR_GROWTH_CEILING: Dict[str, float] = {
    "IT": 0.18,
    "Consumer / FMCG": 0.15,
    "Pharma": 0.16,
    "Auto": 0.15,
    "Industrials / Capital Goods": 0.18,
    "Metals & Mining": 0.12,
    "Cement": 0.12,
    "Chemicals / Specialty": 0.20,
    "Power / Utilities": 0.10,
    "Realty": 0.18,
    "Telecom": 0.10,
    "Oil & Gas": 0.10,
    "Retail / QSR": 0.22,
    "Media": 0.15,
    "Default": 0.16,
}

TERMINAL_GROWTH = 0.045    # India long-run nominal GDP proxy
EXPLICIT_YEARS = 10
GROWTH_LOWER_BOUND = -0.50  # solver floor
GROWTH_UPPER_BOUND = 1.00   # solver ceiling


# Map the project's canonical sector tags (from TICKER_SECTOR_MAP in config) +
# any free-text fallback from screener.in to our reverse-DCF buckets above.
_TAG_TO_BUCKET: Dict[str, str] = {
    "IT": "IT",
    "FMCG": "Consumer / FMCG",
    "Pharmaceuticals": "Pharma",
    "Healthcare": "Pharma",
    "Auto": "Auto",
    "Auto Ancillaries": "Auto",
    "Capital Goods": "Industrials / Capital Goods",
    "Defence": "Industrials / Capital Goods",
    "Steel": "Metals & Mining",
    "Metals": "Metals & Mining",
    "Cement": "Cement",
    "Chemicals": "Chemicals / Specialty",
    "Fertilizers": "Chemicals / Specialty",
    "Power": "Power / Utilities",
    "Renewable Energy": "Power / Utilities",
    "Realty": "Realty",
    "Telecom": "Telecom",
    "Oil & Gas": "Oil & Gas",
    "Retailing": "Retail / QSR",
    "Hotels": "Retail / QSR",
    "Consumer Durables": "Consumer / FMCG",
    "Internet": "Retail / QSR",
    "Logistics": "Industrials / Capital Goods",
    "Aviation": "Industrials / Capital Goods",
    "Sugar": "Chemicals / Specialty",
    "Textiles": "Default",
    "Media": "Media",
}

# Financials — excluded from FCF-DCF; use embedded value / P-B instead.
_FINANCIAL_TAGS = {"Banks", "Finance", "Insurance"}


def _sector_bucket(ticker: str, raw: Optional[str]) -> str:
    """Resolve ticker → canonical bucket. Prefers TICKER_SECTOR_MAP (curated),
    falls back to screener.in's free-text sector with keyword heuristics."""
    tag = TICKER_SECTOR_MAP.get(ticker.upper())
    if tag and tag in _TAG_TO_BUCKET:
        return _TAG_TO_BUCKET[tag]
    if not raw:
        return "Default"
    s = raw.lower()
    if any(k in s for k in ["software", "it ", "computer"]): return "IT"
    if any(k in s for k in ["fmcg", "consumer food", "personal care"]): return "Consumer / FMCG"
    if "pharma" in s or "healthcare" in s: return "Pharma"
    if any(k in s for k in ["automobile", "ancillaries", "tyres"]): return "Auto"
    if any(k in s for k in ["engineering", "capital goods", "industrial"]): return "Industrials / Capital Goods"
    if any(k in s for k in ["steel", "metals", "mining"]): return "Metals & Mining"
    if "cement" in s: return "Cement"
    if any(k in s for k in ["chemicals", "specialty", "fertilizer"]): return "Chemicals / Specialty"
    if any(k in s for k in ["power", "utility"]): return "Power / Utilities"
    if "realty" in s or "real estate" in s: return "Realty"
    if "telecom" in s: return "Telecom"
    if any(k in s for k in ["oil", "gas", "refinery"]): return "Oil & Gas"
    if any(k in s for k in ["retail", "restaurant", "qsr"]): return "Retail / QSR"
    if "media" in s: return "Media"
    return "Default"


def _is_financial(ticker: str, raw: Optional[str]) -> bool:
    """Check curated map first, then free-text fallback."""
    tag = TICKER_SECTOR_MAP.get(ticker.upper())
    if tag and tag in _FINANCIAL_TAGS:
        return True
    if not raw:
        return False
    s = raw.lower()
    return any(k in s for k in ["bank", "nbfc", "insurance", "financial services",
                                "asset management", "exchange", "broker"])


# =========================================================================
# Core DCF math
# =========================================================================

def two_stage_npv(fcf0: float, g: float, wacc: float, terminal_g: float,
                  years: int = EXPLICIT_YEARS) -> float:
    """NPV of a two-stage FCF stream. Returns Rs in the same unit as fcf0."""
    if wacc <= terminal_g:
        return float("nan")
    pv_explicit = 0.0
    for t in range(1, years + 1):
        fcf_t = fcf0 * (1 + g) ** t
        pv_explicit += fcf_t / (1 + wacc) ** t
    fcf_n = fcf0 * (1 + g) ** years
    tv = fcf_n * (1 + terminal_g) / (wacc - terminal_g)
    pv_terminal = tv / (1 + wacc) ** years
    return pv_explicit + pv_terminal


def solve_implied_growth(fcf0: float, ev: float, wacc: float,
                         terminal_g: float = TERMINAL_GROWTH,
                         years: int = EXPLICIT_YEARS) -> Optional[float]:
    """Bisect on g such that two_stage_npv(g) ≈ ev. Returns implied growth, or None
    if EV is outside the bracketable range."""
    if fcf0 is None or fcf0 <= 0 or ev is None or ev <= 0 or wacc <= 0:
        return None

    lo, hi = GROWTH_LOWER_BOUND, GROWTH_UPPER_BOUND
    npv_lo = two_stage_npv(fcf0, lo, wacc, terminal_g, years)
    npv_hi = two_stage_npv(fcf0, hi, wacc, terminal_g, years)

    if pd.isna(npv_lo) or pd.isna(npv_hi):
        return None
    # NPV monotonic increasing in g (for g < wacc-eps). EV must lie in bracket.
    if ev <= npv_lo:
        return float(lo)
    if ev >= npv_hi:
        return float(hi)

    for _ in range(80):  # ample for 0.0001 precision
        mid = (lo + hi) / 2
        npv = two_stage_npv(fcf0, mid, wacc, terminal_g, years)
        if pd.isna(npv):
            return None
        if abs(npv - ev) / max(ev, 1) < 1e-5:
            return float(mid)
        if npv < ev:
            lo = mid
        else:
            hi = mid
    return float((lo + hi) / 2)


# =========================================================================
# Per-ticker analyzer
# =========================================================================

@dataclass
class ReverseDCFReport:
    ticker: str
    sector_bucket: str
    fcf_base_cr: Optional[float] = None
    mcap_cr: Optional[float] = None
    debt_cr: Optional[float] = None
    ev_cr: Optional[float] = None
    wacc: Optional[float] = None
    terminal_g: float = TERMINAL_GROWTH
    implied_growth: Optional[float] = None
    historical_sales_cagr_5y: Optional[float] = None
    historical_profit_cagr_5y: Optional[float] = None
    sector_ceiling: Optional[float] = None
    verdict: str = "na"           # "cheap" | "fair" | "stretched" | "na"
    note: str = ""
    scenarios: Dict[str, Any] = field(default_factory=dict)
    fetched_ok: bool = True


def _avg_recent(series: pd.Series, n: int = 3) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    s = s.iloc[-n:] if len(s) >= n else s
    return float(s.mean())


def _cagr(latest: Optional[float], earliest: Optional[float], years: int) -> Optional[float]:
    if earliest is None or earliest <= 0 or latest is None or years <= 0:
        return None
    try:
        return (latest / earliest) ** (1 / years) - 1
    except Exception:
        return None


def analyze(ticker: str, adapter: Optional[ScreenerPremiumAdapter] = None) -> ReverseDCFReport:
    adapter = adapter or ScreenerPremiumAdapter()

    # Current fundamentals → market cap, sector, latest borrowings
    try:
        f = adapter.fundamentals(ticker)
    except Exception as exc:
        log.warning("reverse_dcf fundamentals %s: %s", ticker, exc)
        return ReverseDCFReport(ticker=ticker, sector_bucket="Default", fetched_ok=False,
                                note=f"fundamentals fetch failed: {exc}")

    if f.get("error"):
        return ReverseDCFReport(ticker=ticker, sector_bucket="Default", fetched_ok=False,
                                note=f"fundamentals: {f['error']}")

    raw_sector = f.get("sector")
    if _is_financial(ticker, raw_sector):
        return ReverseDCFReport(ticker=ticker, sector_bucket="Financials", fetched_ok=False,
                                note="skipped (financial — use embedded value / P-B framework)")

    bucket = _sector_bucket(ticker, raw_sector)
    wacc = SECTOR_WACC.get(bucket, SECTOR_WACC["Default"])
    ceiling = SECTOR_GROWTH_CEILING.get(bucket, SECTOR_GROWTH_CEILING["Default"])

    mcap = f.get("market_cap_cr")

    # Historical for FCF base, debt, and historical CAGRs
    try:
        fin = adapter.historical_financials(ticker)
    except Exception as exc:
        log.warning("reverse_dcf history %s: %s", ticker, exc)
        return ReverseDCFReport(ticker=ticker, sector_bucket=bucket, fetched_ok=False,
                                note=f"history fetch failed: {exc}")

    cf = fin.get("cashflow", pd.DataFrame())
    pnl = fin.get("pnl", pd.DataFrame())
    bs = fin.get("balance_sheet", pd.DataFrame())

    # FCF base — 3y mean of "Free Cash Flow" row from cashflow
    fcf_row = None
    if not cf.empty:
        for idx in cf.index:
            if "free cash flow" in str(idx).lower():
                fcf_row = pd.to_numeric(cf.loc[idx], errors="coerce")
                break
    fcf_base = _avg_recent(fcf_row, n=3) if fcf_row is not None else None

    # Debt — latest "Borrowings" from BS
    debt = None
    if not bs.empty:
        for idx in bs.index:
            if "borrowings" in str(idx).lower():
                series = pd.to_numeric(bs.loc[idx], errors="coerce").dropna()
                if not series.empty:
                    debt = float(series.iloc[-1])
                break

    # Historical CAGRs from PnL (sales, profit) — 5y
    sales_cagr = profit_cagr = None
    if not pnl.empty:
        sales_row = None
        np_row = None
        for idx in pnl.index:
            li = str(idx).lower()
            if sales_row is None and ("sales" in li or "revenue" in li):
                sales_row = pd.to_numeric(pnl.loc[idx], errors="coerce")
            if np_row is None and "net profit" in li:
                np_row = pd.to_numeric(pnl.loc[idx], errors="coerce")
        if sales_row is not None and len(sales_row.dropna()) >= 5:
            s = sales_row.dropna()
            sales_cagr = _cagr(float(s.iloc[-1]), float(s.iloc[-6]) if len(s) >= 6 else float(s.iloc[0]),
                               5 if len(s) >= 6 else len(s) - 1)
        if np_row is not None and len(np_row.dropna()) >= 5:
            s = np_row.dropna()
            profit_cagr = _cagr(float(s.iloc[-1]), float(s.iloc[-6]) if len(s) >= 6 else float(s.iloc[0]),
                                5 if len(s) >= 6 else len(s) - 1)

    if fcf_base is None or fcf_base <= 0 or mcap is None:
        note = "FCF base negative or missing — cyclical low or capex peak; reverse-DCF undefined"
        return ReverseDCFReport(ticker=ticker, sector_bucket=bucket, fcf_base_cr=fcf_base,
                                mcap_cr=mcap, debt_cr=debt, wacc=wacc, sector_ceiling=ceiling,
                                historical_sales_cagr_5y=sales_cagr,
                                historical_profit_cagr_5y=profit_cagr,
                                verdict="na", note=note, fetched_ok=True)

    ev = float(mcap) + float(debt or 0)
    implied = solve_implied_growth(fcf_base, ev, wacc, TERMINAL_GROWTH)

    # Verdict logic
    if implied is None:
        verdict = "na"; note = "implied growth not solvable"
    else:
        # Compare to the better-anchored of (sales CAGR, profit CAGR) — for
        # high-quality compounders profit CAGR > sales CAGR; for cyclicals
        # sales CAGR is the better long-run anchor.
        ref = sales_cagr if sales_cagr is not None else profit_cagr
        if ref is not None and implied < ref - 0.02:
            verdict = "cheap"
            note = (f"implied {implied*100:.1f}% < 5y reference {ref*100:.1f}% — market less "
                    "optimistic than the business has shown")
        elif implied > ceiling:
            verdict = "stretched"
            note = (f"implied {implied*100:.1f}% > sector ceiling {ceiling*100:.0f}% — priced "
                    "for perfection vs sector norms")
        else:
            verdict = "fair"
            note = (f"implied {implied*100:.1f}% within range "
                    f"(ref {ref*100:.1f}% if ref else 'n/a', ceiling {ceiling*100:.0f}%)"
                    if ref else
                    f"implied {implied*100:.1f}%, ceiling {ceiling*100:.0f}%")

    # Scenario table — bear / base / bull on WACC
    scenarios = {}
    for name, w_delta in [("bear (+1.5% WACC)", 0.015), ("base", 0.0), ("bull (-1.5% WACC)", -0.015)]:
        w = max(0.06, wacc + w_delta)
        g_sc = solve_implied_growth(fcf_base, ev, w, TERMINAL_GROWTH)
        scenarios[name] = {"wacc": round(w, 3),
                           "implied_growth": round(g_sc, 4) if g_sc is not None else None}

    return ReverseDCFReport(
        ticker=ticker, sector_bucket=bucket,
        fcf_base_cr=round(fcf_base, 1),
        mcap_cr=round(mcap, 0) if mcap else None,
        debt_cr=round(debt, 0) if debt else None,
        ev_cr=round(ev, 0),
        wacc=wacc, terminal_g=TERMINAL_GROWTH,
        implied_growth=round(implied, 4) if implied is not None else None,
        historical_sales_cagr_5y=round(sales_cagr, 4) if sales_cagr is not None else None,
        historical_profit_cagr_5y=round(profit_cagr, 4) if profit_cagr is not None else None,
        sector_ceiling=ceiling,
        verdict=verdict, note=note,
        scenarios=scenarios, fetched_ok=True,
    )


# =========================================================================
# Universe screener
# =========================================================================

class ReverseDCFScreener(Screener):
    framework = "reverse_dcf"

    def __init__(self, adapter: Optional[ScreenerPremiumAdapter] = None):
        self.adapter = adapter or ScreenerPremiumAdapter()

    def _criteria(self) -> Dict[str, str]:
        return {
            "model": "two-stage DCF, 10y explicit + perpetuity",
            "terminal_growth": f"{TERMINAL_GROWTH*100:.1f}% (India long-run nominal GDP proxy)",
            "wacc_source": "sector prior (see SECTOR_WACC)",
            "fcf_base": "3y average of screener.in Free Cash Flow row",
            "ev_proxy": "market cap + total borrowings (cash not netted)",
            "verdict": "cheap: implied < 5y CAGR - 2pp; stretched: implied > sector ceiling",
        }

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
                "sector": r.sector_bucket,
                "verdict": r.verdict,
                "implied_g_pct":  round(r.implied_growth * 100, 1) if r.implied_growth is not None else None,
                "sales_cagr_5y_pct": round(r.historical_sales_cagr_5y * 100, 1) if r.historical_sales_cagr_5y is not None else None,
                "profit_cagr_5y_pct": round(r.historical_profit_cagr_5y * 100, 1) if r.historical_profit_cagr_5y is not None else None,
                "ceiling_pct": round(r.sector_ceiling * 100, 0) if r.sector_ceiling is not None else None,
                "wacc_pct": round(r.wacc * 100, 1) if r.wacc is not None else None,
                "fcf_cr": r.fcf_base_cr,
                "mcap_cr": r.mcap_cr,
                "note": r.note,
            })

        df = pd.DataFrame(rows)
        # Sort: cheap names first (lowest implied growth)
        if not df.empty and "implied_g_pct" in df.columns:
            df = df.sort_values(["verdict", "implied_g_pct"],
                                ascending=[True, True]).reset_index(drop=True)

        return ScreenResult(
            framework=self.framework,
            candidates=df,
            rejected_count=rejected,
            notes=[
                "Reverse-DCF infers the long-term FCF growth rate the market is paying for.",
                "**Cheap** = market expects less than the business has historically delivered.",
                "**Stretched** = market expects more than the sector has ever sustainably grown.",
                "Cyclicals (metals, autos, capex names) need normalised FCF — treat results with care.",
                "Financials are excluded; use embedded value / P-B for those.",
            ],
            criteria=self._criteria(),
        )
