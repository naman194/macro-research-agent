"""Earnings-quality / forensic-accounting screen.

What this does that a ratio screener doesn't:
  - Reads cash flow + accruals quality, not just P&L beauty
  - Tracks 8-10 year drift, not just latest snapshot — quality erosion is
    almost always gradual
  - Flags divergence (debt growing faster than profit, depreciation slowing
    vs asset base, working capital ballooning relative to sales)

The composite ForensicRiskScore (0-100, higher = more risk) is a *prior* for
where to look harder. It is NOT a verdict. A 70+ score means open the
annual report; a 20 means the numbers are clean. Use alongside structural
risk + management quality, not as a standalone signal.

Inspired by:
  - Sloan (1996) — total accruals predict negative future returns
  - Beneish (1999) M-score — eight ratios for earnings manipulation likelihood
  - Indian forensic cases: Manpasand, DHFL, Yes Bank, Vakrangee — every one
    of them flagged on cash conversion + accruals + debt divergence years
    before the market priced it in.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from src.data.screener_premium import ScreenerPremiumAdapter
from src.screens.base import Screener, ScreenResult

log = logging.getLogger(__name__)


# ---------- thresholds ----------
# Tuned for Indian universe; revisit if false-positive rate too high.
CASH_CONV_HEALTHY = 0.80   # CFO/PAT >= 0.80 sustained = clean
CASH_CONV_AMBER = 0.60     # 0.60–0.80 = watch
CASH_CONV_RED = 0.40       # <0.40 sustained = serious flag

SLOAN_AMBER = 0.06         # accruals/TA > 6% = aggressive
SLOAN_RED = 0.10           # > 10% = Sloan's classic red zone

WC_DRIFT_AMBER = 0.10      # WC/Sales rising >10pp over 5y
WC_DRIFT_RED = 0.20

BENEISH_SGI_AMBER = 1.40   # 40% YoY sales growth
BENEISH_SGI_RED = 1.80
BENEISH_DEPI_AMBER = 1.05  # depreciation slowing 5%+
BENEISH_DEPI_RED = 1.15

DEBT_DIVERGENCE_AMBER = 1.5  # debt CAGR / profit CAGR
DEBT_DIVERGENCE_RED = 3.0

INT_COVER_AMBER = 3.0
INT_COVER_RED = 1.5

OI_SHARE_AMBER = 0.20      # other income / PBT
OI_SHARE_RED = 0.35

# Composite weights (sum = 1.0)
WEIGHTS = {
    "cash_conv":       0.22,
    "sloan_accruals":  0.15,
    "wc_drift":        0.10,
    "beneish_sgi":     0.08,
    "beneish_depi":    0.10,
    "debt_divergence": 0.12,
    "int_cover":       0.13,
    "oi_share":        0.05,
    "lvgi":            0.05,
}


# =========================================================================
# Result container
# =========================================================================

@dataclass
class MetricResult:
    name: str
    latest: Optional[float]
    series: pd.Series                 # year -> value
    score: float                      # 0.0 (clean) to 1.0 (severe)
    verdict: str                      # "green" | "amber" | "red" | "na"
    note: str                         # 1-line human read


@dataclass
class ForensicReport:
    ticker: str
    composite_score: float            # 0-100, higher = riskier
    verdict: str                      # "green" | "amber" | "red"
    metrics: Dict[str, MetricResult] = field(default_factory=dict)
    headline_flag: Optional[str] = None  # one-line worst-finding for surfacing in brief
    fetched_ok: bool = True


# =========================================================================
# Row resolution — screener.in label variants
# =========================================================================

def _row(df: pd.DataFrame, candidates: List[str]) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    for c in candidates:
        for idx in df.index:
            if c.lower() in str(idx).lower():
                return df.loc[idx]
    return None


def _series_to_float(s: Optional[pd.Series]) -> pd.Series:
    if s is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(s, errors="coerce")


def _verdict(score: float) -> str:
    if score >= 0.66: return "red"
    if score >= 0.33: return "amber"
    return "green"


def _is_financial(pnl: pd.DataFrame, bs: pd.DataFrame) -> bool:
    """Detect banks / NBFCs / insurers from their balance-sheet shape.

    Heuristic: if (Sales / TA) < 15% across the window AND FA / TA < 5%,
    this is almost certainly a financial. For those, several forensics
    metrics (working-capital intensity, depreciation slowdown, sales-growth
    index, other-income share) are structurally meaningless or misleading.
    """
    if pnl is None or pnl.empty or bs is None or bs.empty:
        return False
    sales = _series_to_float(_row(pnl, ["Sales", "Revenue", "Interest Income"]))
    ta = _series_to_float(_row(bs, ["Total Assets", "Total Liabilities"]))
    fa = _series_to_float(_row(bs, ["Fixed Assets"]))
    if sales.empty or ta.empty:
        return False
    common = [y for y in sales.index if y in ta.index
              and pd.notna(sales[y]) and pd.notna(ta[y]) and ta[y] > 0]
    if not common:
        return False
    turnover = sum(float(sales[y]) for y in common) / sum(float(ta[y]) for y in common)
    if turnover >= 0.15:
        return False
    if fa.empty:
        return True
    fa_common = [y for y in common if y in fa.index and pd.notna(fa[y])]
    if not fa_common:
        return True
    fa_share = sum(float(fa[y]) for y in fa_common) / sum(float(ta[y]) for y in fa_common)
    return fa_share < 0.05


def _cagr(latest: float, earliest: float, years: int) -> Optional[float]:
    if earliest is None or earliest <= 0 or latest is None or years <= 0:
        return None
    try:
        return (latest / earliest) ** (1 / years) - 1
    except Exception:
        return None


# =========================================================================
# Individual metric calculators
# Each returns MetricResult. Each is independent so we can show partial reports
# when some data is missing.
# =========================================================================

def metric_cash_conversion(pnl: pd.DataFrame, cf: pd.DataFrame) -> MetricResult:
    """CFO / PAT — the single most predictive earnings-quality metric in India."""
    pat = _series_to_float(_row(pnl, ["Net Profit"]))
    cfo = _series_to_float(_row(cf, ["Cash from Operating", "Operating Activity"]))
    if pat.empty or cfo.empty:
        return MetricResult("cash_conv", None, pd.Series(dtype=float), 0.0, "na",
                            "CFO or PAT not available")

    # Align by intersecting years
    yrs = [y for y in pat.index if y in cfo.index and pd.notna(pat[y]) and pd.notna(cfo[y]) and pat[y] != 0]
    series = pd.Series({y: cfo[y] / pat[y] for y in yrs})

    if series.empty:
        return MetricResult("cash_conv", None, series, 0.0, "na", "no overlapping years")

    # 5y mean ignores noise — what matters is the level, not single-year blips
    recent = series.iloc[-5:] if len(series) >= 5 else series
    mean = recent.mean()
    latest = series.iloc[-1]

    # Score: 0 if mean >= 0.80, 1 if mean <= 0.20, linear between
    if mean >= CASH_CONV_HEALTHY:
        score = 0.0
    elif mean <= 0.20:
        score = 1.0
    else:
        score = (CASH_CONV_HEALTHY - mean) / (CASH_CONV_HEALTHY - 0.20)
    score = max(0.0, min(1.0, float(score)))

    # Trend penalty: if last 3y materially below first 3y of recent window
    if len(recent) >= 5:
        early = recent.iloc[:2].mean()
        late = recent.iloc[-2:].mean()
        if pd.notna(early) and pd.notna(late) and early - late > 0.20:
            score = min(1.0, score + 0.15)

    note = f"5y avg CFO/PAT = {mean:.2f} (latest {latest:.2f})"
    return MetricResult("cash_conv", float(latest), series, score, _verdict(score), note)


def metric_sloan_accruals(pnl: pd.DataFrame, cf: pd.DataFrame, bs: pd.DataFrame) -> MetricResult:
    """(NI - CFO) / Avg Total Assets. Sloan (1996): high accruals predict reversal."""
    pat = _series_to_float(_row(pnl, ["Net Profit"]))
    cfo = _series_to_float(_row(cf, ["Cash from Operating", "Operating Activity"]))
    ta = _series_to_float(_row(bs, ["Total Assets", "Total Liabilities"]))  # screener: TL = TA
    if pat.empty or cfo.empty or ta.empty:
        return MetricResult("sloan_accruals", None, pd.Series(dtype=float), 0.0, "na",
                            "missing inputs")

    yrs = sorted(set(pat.index) & set(cfo.index) & set(ta.index),
                 key=lambda x: list(pat.index).index(x))
    rows = {}
    prev_ta = None
    for y in yrs:
        if pd.notna(pat[y]) and pd.notna(cfo[y]) and pd.notna(ta[y]) and ta[y] > 0:
            avg_ta = (ta[y] + prev_ta) / 2 if prev_ta else ta[y]
            rows[y] = (pat[y] - cfo[y]) / avg_ta
            prev_ta = ta[y]
        else:
            prev_ta = ta[y] if pd.notna(ta[y]) else prev_ta
    series = pd.Series(rows)
    if series.empty:
        return MetricResult("sloan_accruals", None, series, 0.0, "na", "no valid year")

    recent = series.iloc[-5:] if len(series) >= 5 else series
    mean = recent.mean()
    latest = series.iloc[-1]

    if mean <= 0:
        score = 0.0
    elif mean >= SLOAN_RED:
        score = 1.0
    else:
        score = mean / SLOAN_RED
    score = max(0.0, min(1.0, float(score)))

    note = f"5y mean accruals/TA = {mean*100:.1f}% (latest {latest*100:.1f}%)"
    return MetricResult("sloan_accruals", float(latest), series, score, _verdict(score), note)


def metric_wc_drift(pnl: pd.DataFrame, bs: pd.DataFrame) -> MetricResult:
    """Working capital intensity = (TA - FA - CWIP - Investments) / Sales.
    Sustained rise = receivables/inventory bloat → revenue without cash.

    Not meaningful for banks/NBFCs (assets ARE the loan book, sales = interest
    income). We detect financials by Sales/TA < 0.15 and skip the metric."""
    sales = _series_to_float(_row(pnl, ["Sales", "Revenue", "Interest Income"]))
    ta = _series_to_float(_row(bs, ["Total Assets", "Total Liabilities"]))
    fa = _series_to_float(_row(bs, ["Fixed Assets"]))
    cwip = _series_to_float(_row(bs, ["CWIP"]))
    inv = _series_to_float(_row(bs, ["Investments"]))

    if sales.empty or ta.empty:
        return MetricResult("wc_drift", None, pd.Series(dtype=float), 0.0, "na", "missing inputs")

    # Financials guard: if turnover (sales/TA) is < 15% across the window, this
    # is almost certainly a bank/NBFC/insurer and WC ratio is meaningless.
    common = [y for y in sales.index if y in ta.index
              and pd.notna(sales[y]) and pd.notna(ta[y]) and ta[y] > 0]
    if common:
        turnover = sum(float(sales[y]) for y in common) / sum(float(ta[y]) for y in common)
        if turnover < 0.15:
            return MetricResult("wc_drift", None, pd.Series(dtype=float), 0.0, "na",
                                "skipped (financial — WC intensity not meaningful)")

    yrs = sorted(set(sales.index) & set(ta.index),
                 key=lambda x: list(sales.index).index(x))
    rows = {}
    for y in yrs:
        if pd.isna(sales[y]) or sales[y] <= 0 or pd.isna(ta[y]):
            continue
        fa_v = float(fa[y]) if (not fa.empty and y in fa.index and pd.notna(fa[y])) else 0.0
        cw_v = float(cwip[y]) if (not cwip.empty and y in cwip.index and pd.notna(cwip[y])) else 0.0
        in_v = float(inv[y]) if (not inv.empty and y in inv.index and pd.notna(inv[y])) else 0.0
        op_assets = float(ta[y]) - fa_v - cw_v - in_v
        rows[y] = op_assets / float(sales[y])

    series = pd.Series(rows)
    if len(series) < 3:
        return MetricResult("wc_drift", None, series, 0.0, "na", "need 3+ yrs")

    early = series.iloc[:2].mean()
    late = series.iloc[-2:].mean()
    drift = late - early
    latest = series.iloc[-1]

    if drift <= 0:
        score = 0.0
    elif drift >= WC_DRIFT_RED:
        score = 1.0
    else:
        score = drift / WC_DRIFT_RED
    score = max(0.0, min(1.0, float(score)))

    note = f"WC/Sales drift +{drift*100:.0f}pp over period (latest {latest*100:.0f}%)"
    return MetricResult("wc_drift", float(latest), series, score, _verdict(score), note)


def metric_beneish_sgi(pnl: pd.DataFrame) -> MetricResult:
    """Beneish SGI = Sales_t / Sales_{t-1}. Aggressive growth often precedes manipulation."""
    sales = _series_to_float(_row(pnl, ["Sales", "Revenue", "Interest Income"]))
    if sales.empty or len(sales) < 2:
        return MetricResult("beneish_sgi", None, pd.Series(dtype=float), 0.0, "na", "insufficient")

    yrs = list(sales.index)
    rows = {}
    for i in range(1, len(yrs)):
        prev, cur = sales.iloc[i - 1], sales.iloc[i]
        if pd.notna(prev) and prev > 0 and pd.notna(cur):
            rows[yrs[i]] = cur / prev
    series = pd.Series(rows)
    if series.empty:
        return MetricResult("beneish_sgi", None, series, 0.0, "na", "no valid year")

    recent = series.iloc[-3:]
    max_recent = recent.max()
    latest = series.iloc[-1]

    if max_recent <= 1.20:
        score = 0.0
    elif max_recent >= BENEISH_SGI_RED:
        score = 1.0
    else:
        score = (max_recent - 1.20) / (BENEISH_SGI_RED - 1.20)
    score = max(0.0, min(1.0, float(score)))

    note = f"Max recent SGI = {max_recent:.2f}x (latest {latest:.2f}x)"
    return MetricResult("beneish_sgi", float(latest), series, score, _verdict(score), note)


def metric_beneish_depi(pnl: pd.DataFrame, bs: pd.DataFrame) -> MetricResult:
    """DEPI = Depr_{t-1}/(Depr_{t-1}+FA_{t-1}) ÷ same_t. >1 = slowing depreciation."""
    depr = _series_to_float(_row(pnl, ["Depreciation"]))
    fa = _series_to_float(_row(bs, ["Fixed Assets"]))
    ta = _series_to_float(_row(bs, ["Total Assets", "Total Liabilities"]))
    if depr.empty or fa.empty:
        return MetricResult("beneish_depi", None, pd.Series(dtype=float), 0.0, "na", "missing")

    # Skip for asset-light businesses (FA/TA < 5% — financials, IT services with
    # minimal capex). Depreciation slowdown signal is noise there.
    if not ta.empty:
        common = [y for y in fa.index if y in ta.index
                  and pd.notna(fa[y]) and pd.notna(ta[y]) and ta[y] > 0]
        if common:
            fa_share = sum(float(fa[y]) for y in common) / sum(float(ta[y]) for y in common)
            if fa_share < 0.05:
                return MetricResult("beneish_depi", None, pd.Series(dtype=float), 0.0, "na",
                                    "skipped (asset-light — DEPI not meaningful)")

    yrs = sorted(set(depr.index) & set(fa.index), key=lambda x: list(depr.index).index(x))
    ratio = {}
    for y in yrs:
        d, f = depr.get(y), fa.get(y)
        if pd.notna(d) and pd.notna(f) and (d + f) > 0:
            ratio[y] = d / (d + f)
    rs = pd.Series(ratio)
    if len(rs) < 2:
        return MetricResult("beneish_depi", None, rs, 0.0, "na", "need 2+ yrs")

    rows = {}
    for i in range(1, len(rs)):
        prev, cur = rs.iloc[i - 1], rs.iloc[i]
        if cur > 0:
            rows[rs.index[i]] = prev / cur
    series = pd.Series(rows)
    if series.empty:
        return MetricResult("beneish_depi", None, series, 0.0, "na", "no valid year")

    recent = series.iloc[-3:]
    max_recent = recent.max()
    latest = series.iloc[-1]

    if max_recent <= 1.0:
        score = 0.0
    elif max_recent >= BENEISH_DEPI_RED:
        score = 1.0
    else:
        score = (max_recent - 1.0) / (BENEISH_DEPI_RED - 1.0)
    score = max(0.0, min(1.0, float(score)))

    note = f"Max recent DEPI = {max_recent:.2f} (>1 = slowing depreciation)"
    return MetricResult("beneish_depi", float(latest), series, score, _verdict(score), note)


def metric_debt_divergence(pnl: pd.DataFrame, bs: pd.DataFrame) -> MetricResult:
    """Debt CAGR vs Profit CAGR over 5y. >>1 = borrowing to look profitable."""
    pat = _series_to_float(_row(pnl, ["Net Profit"]))
    debt = _series_to_float(_row(bs, ["Borrowings"]))
    if pat.empty or debt.empty:
        return MetricResult("debt_divergence", None, pd.Series(dtype=float), 0.0, "na", "missing")

    yrs = [y for y in pat.index if y in debt.index]
    if len(yrs) < 4:
        return MetricResult("debt_divergence", None, pd.Series(dtype=float), 0.0, "na", "need 4+ yrs")

    window = yrs[-5:] if len(yrs) >= 5 else yrs
    pat_start, pat_end = pat[window[0]], pat[window[-1]]
    debt_start, debt_end = debt[window[0]], debt[window[-1]]

    debt_cagr = _cagr(debt_end, debt_start, len(window) - 1)
    pat_cagr = _cagr(pat_end, pat_start, len(window) - 1)

    if debt_cagr is None or pat_cagr is None or debt_cagr <= 0:
        return MetricResult("debt_divergence", None, pd.Series(dtype=float), 0.0, "na", "cannot compute")

    # If debt shrinking or profit growing faster than debt — clean
    if pat_cagr >= debt_cagr or debt_cagr <= 0.05:
        score = 0.0
        ratio = debt_cagr / pat_cagr if pat_cagr > 0 else None
    else:
        # Ratio of growth rates. pat negative = mega red flag.
        if pat_cagr <= 0:
            score = 1.0
            ratio = None
        else:
            ratio = debt_cagr / pat_cagr
            if ratio >= DEBT_DIVERGENCE_RED:
                score = 1.0
            elif ratio <= 1.0:
                score = 0.0
            else:
                score = (ratio - 1.0) / (DEBT_DIVERGENCE_RED - 1.0)
            score = max(0.0, min(1.0, float(score)))

    series = pd.Series({"debt_cagr": debt_cagr, "pat_cagr": pat_cagr})
    if pat_cagr <= 0:
        note = f"Debt CAGR {debt_cagr*100:.0f}%, PAT shrinking ({pat_cagr*100:.0f}%)"
    else:
        note = f"Debt CAGR {debt_cagr*100:.0f}% vs PAT CAGR {pat_cagr*100:.0f}% (ratio {ratio:.1f}x)"
    return MetricResult("debt_divergence", float(score), series, score, _verdict(score), note)


def metric_interest_coverage(pnl: pd.DataFrame) -> MetricResult:
    """(OP + Other Income) / Interest. Trend down + level below 3 = stress."""
    op = _series_to_float(_row(pnl, ["Operating Profit"]))
    oi = _series_to_float(_row(pnl, ["Other Income"]))
    interest = _series_to_float(_row(pnl, ["Interest"]))
    if op.empty or interest.empty:
        return MetricResult("int_cover", None, pd.Series(dtype=float), 0.0, "na", "missing")

    yrs = [y for y in op.index if y in interest.index]
    rows = {}
    for y in yrs:
        i_val = interest.get(y)
        if pd.isna(i_val) or i_val <= 0:
            continue
        ebit = float(op.get(y, 0) or 0) + float(oi.get(y, 0) or 0 if not oi.empty else 0)
        rows[y] = ebit / float(i_val)
    series = pd.Series(rows)
    if series.empty:
        return MetricResult("int_cover", None, series, 0.0, "na", "no debt cost or all zero")

    recent = series.iloc[-3:] if len(series) >= 3 else series
    mean = recent.mean()
    latest = series.iloc[-1]

    if mean >= 6.0:
        score = 0.0
    elif mean <= INT_COVER_RED:
        score = 1.0
    else:
        score = (6.0 - mean) / (6.0 - INT_COVER_RED)
    score = max(0.0, min(1.0, float(score)))

    note = f"3y avg interest cover = {mean:.1f}x (latest {latest:.1f}x)"
    return MetricResult("int_cover", float(latest), series, score, _verdict(score), note)


def metric_oi_share(pnl: pd.DataFrame) -> MetricResult:
    """Other Income / PBT. >25% sustained = profits not from core operations."""
    oi = _series_to_float(_row(pnl, ["Other Income"]))
    pbt = _series_to_float(_row(pnl, ["Profit before tax", "PBT"]))
    if oi.empty or pbt.empty:
        return MetricResult("oi_share", None, pd.Series(dtype=float), 0.0, "na", "missing")

    yrs = [y for y in oi.index if y in pbt.index]
    rows = {}
    for y in yrs:
        p = pbt.get(y)
        if pd.notna(p) and p > 0:
            rows[y] = (float(oi.get(y, 0) or 0)) / float(p)
    series = pd.Series(rows)
    if series.empty:
        return MetricResult("oi_share", None, series, 0.0, "na", "PBT <= 0 or missing")

    recent = series.iloc[-3:]
    mean = recent.mean()
    latest = series.iloc[-1]

    if mean <= 0.10:
        score = 0.0
    elif mean >= 0.50:
        score = 1.0
    else:
        score = (mean - 0.10) / (0.50 - 0.10)
    score = max(0.0, min(1.0, float(score)))

    note = f"3y avg Other Income/PBT = {mean*100:.0f}% (latest {latest*100:.0f}%)"
    return MetricResult("oi_share", float(latest), series, score, _verdict(score), note)


def metric_lvgi(bs: pd.DataFrame) -> MetricResult:
    """Beneish LVGI = ((Debt + OL)/TA)_t ÷ same_{t-1}. >1.1 = leverage spike."""
    debt = _series_to_float(_row(bs, ["Borrowings"]))
    ol = _series_to_float(_row(bs, ["Other Liabilities"]))
    ta = _series_to_float(_row(bs, ["Total Assets", "Total Liabilities"]))
    if debt.empty or ta.empty:
        return MetricResult("lvgi", None, pd.Series(dtype=float), 0.0, "na", "missing")

    yrs = sorted(set(debt.index) & set(ta.index), key=lambda x: list(debt.index).index(x))
    ratio = {}
    for y in yrs:
        d = float(debt.get(y, 0) or 0)
        o = float(ol.get(y, 0) or 0) if not ol.empty else 0
        t = float(ta.get(y, 0) or 0)
        if t > 0:
            ratio[y] = (d + o) / t
    rs = pd.Series(ratio)
    if len(rs) < 2:
        return MetricResult("lvgi", None, rs, 0.0, "na", "need 2+ yrs")

    rows = {}
    for i in range(1, len(rs)):
        prev, cur = rs.iloc[i - 1], rs.iloc[i]
        if prev > 0:
            rows[rs.index[i]] = cur / prev
    series = pd.Series(rows)
    if series.empty:
        return MetricResult("lvgi", None, series, 0.0, "na", "no ratios")

    recent = series.iloc[-3:]
    max_recent = recent.max()
    latest = series.iloc[-1]

    if max_recent <= 1.0:
        score = 0.0
    elif max_recent >= 1.30:
        score = 1.0
    else:
        score = (max_recent - 1.0) / (1.30 - 1.0)
    score = max(0.0, min(1.0, float(score)))

    note = f"Max LVGI = {max_recent:.2f} (>1 = leverage rising vs assets)"
    return MetricResult("lvgi", float(latest), series, score, _verdict(score), note)


# =========================================================================
# Single-ticker orchestrator
# =========================================================================

ALL_METRICS = [
    "cash_conv", "sloan_accruals", "wc_drift",
    "beneish_sgi", "beneish_depi", "debt_divergence",
    "int_cover", "oi_share", "lvgi",
]


def analyze(ticker: str, adapter: Optional[ScreenerPremiumAdapter] = None) -> ForensicReport:
    adapter = adapter or ScreenerPremiumAdapter()
    try:
        fin = adapter.historical_financials(ticker)
    except Exception as exc:
        log.warning("forensics fetch %s: %s", ticker, exc)
        return ForensicReport(ticker=ticker, composite_score=0.0, verdict="na", fetched_ok=False)

    pnl = fin.get("pnl", pd.DataFrame())
    bs = fin.get("balance_sheet", pd.DataFrame())
    cf = fin.get("cashflow", pd.DataFrame())

    if pnl.empty:
        return ForensicReport(ticker=ticker, composite_score=0.0, verdict="na", fetched_ok=False)

    is_fin = _is_financial(pnl, bs)

    metrics: Dict[str, MetricResult] = {
        "cash_conv":       metric_cash_conversion(pnl, cf),
        "sloan_accruals":  metric_sloan_accruals(pnl, cf, bs),
        "wc_drift":        metric_wc_drift(pnl, bs),
        "beneish_sgi":     metric_beneish_sgi(pnl),
        "beneish_depi":    metric_beneish_depi(pnl, bs),
        "debt_divergence": metric_debt_divergence(pnl, bs),
        "int_cover":       metric_interest_coverage(pnl),
        "oi_share":        metric_oi_share(pnl),
        "lvgi":            metric_lvgi(bs),
    }

    # For banks / NBFCs / insurers, structurally noisy metrics get skipped.
    # Real forensic signals for financials (NPA drift, advances vs CASA, credit
    # cost ratio) are a separate v2 effort.
    if is_fin:
        for skip in ("beneish_sgi", "oi_share"):
            old = metrics[skip]
            metrics[skip] = MetricResult(
                skip, None, pd.Series(dtype=float), 0.0, "na",
                "skipped (financial — metric not meaningful for banks/NBFCs)"
            )

    # Composite: weighted sum of scores where verdict != "na"
    total_weight = 0.0
    weighted_sum = 0.0
    for name, m in metrics.items():
        if m.verdict == "na":
            continue
        w = WEIGHTS.get(name, 0.0)
        weighted_sum += w * m.score
        total_weight += w

    composite = (weighted_sum / total_weight * 100.0) if total_weight > 0 else 0.0

    # Headline flag = highest-scoring red metric's note (best one-line for surfacing)
    reds = sorted([m for m in metrics.values() if m.verdict == "red"],
                  key=lambda x: -x.score)
    headline = reds[0].note if reds else None

    return ForensicReport(
        ticker=ticker,
        composite_score=round(composite, 1),
        verdict=("red" if composite >= 60 else ("amber" if composite >= 30 else "green")),
        metrics=metrics,
        headline_flag=headline,
        fetched_ok=True,
    )


# =========================================================================
# Universe screener
# =========================================================================

class ForensicsScreener(Screener):
    framework = "forensics"

    def __init__(self, adapter: Optional[ScreenerPremiumAdapter] = None):
        self.adapter = adapter or ScreenerPremiumAdapter()

    def _criteria(self) -> Dict[str, str]:
        return {
            "cash_conv": f"CFO/PAT 5y mean (red <{CASH_CONV_RED}, amber <{CASH_CONV_HEALTHY})",
            "sloan_accruals": f"(NI - CFO)/Avg TA (red >{SLOAN_RED*100:.0f}%)",
            "wc_drift": f"(TA - FA - Inv)/Sales drift over period (red >{WC_DRIFT_RED*100:.0f}pp)",
            "beneish_sgi": f"Sales growth index (red >{BENEISH_SGI_RED}x)",
            "beneish_depi": f"Depreciation slowdown index (red >{BENEISH_DEPI_RED})",
            "debt_divergence": f"Debt CAGR / PAT CAGR (red >{DEBT_DIVERGENCE_RED}x)",
            "int_cover": f"Interest coverage 3y mean (red <{INT_COVER_RED}x)",
            "oi_share": "Other Income / PBT (red >35% sustained)",
            "lvgi": "Beneish leverage index (red >1.30)",
        }

    def run(self, universe: List[str]) -> ScreenResult:
        rows = []
        rejected = 0
        for t in universe:
            r = analyze(t, self.adapter)
            if not r.fetched_ok:
                rejected += 1
                continue
            row = {
                "ticker": r.ticker,
                "composite_score": r.composite_score,
                "verdict": r.verdict,
                "headline_flag": r.headline_flag or "",
            }
            for name in ALL_METRICS:
                m = r.metrics.get(name)
                row[f"{name}_score"] = round(m.score, 2) if m else None
                row[f"{name}_verdict"] = m.verdict if m else "na"
            rows.append(row)

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)

        return ScreenResult(
            framework=self.framework,
            candidates=df,
            rejected_count=rejected,
            notes=[
                "Composite score 0-100, higher = more quality concern.",
                "Red ≥60, Amber 30-60, Green <30.",
                "This is a *prior* not a verdict — open the AR for red names before any action.",
            ],
            criteria=self._criteria(),
        )
