"""Stock-in-Focus — composes a one-page "name of the day" with chart, fundamentals, peers.

The morning brief picks the highest-scoring Quality+Value or GARP name and renders:
  - 1y price chart with 20/50/200 DMAs (matplotlib PNG)
  - Fundamentals snapshot
  - Peer comparison table (sector peers from screener.in)
  - Simple DCF range (3 scenarios: bear/base/bull)
The PNG is embedded directly in the PDF brief.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")  # headless rendering
import matplotlib.pyplot as plt
import pandas as pd

from src.data.prices import PricesAdapter
from src.data.screener import ScreenerAdapter

log = logging.getLogger(__name__)


# Forensic red names disqualify themselves from being "stock in focus" —
# the daily brief shouldn't anchor on a name where earnings quality is
# questionable, however high it scored on ratios.
FORENSIC_HARD_VETO = 60.0
# DCF "stretched" is a softer veto — we down-rank but don't disqualify (the
# user may still want to discuss it in the brief; it just shouldn't be the
# anchor name).
DCF_DOWNRANK_PENALTY = 15


def pick_focus_ticker(qv_candidates: List[Dict], garp_candidates: List[Dict]) -> Optional[Dict]:
    """Pick the single highest-scoring candidate across Q+V and GARP, after a
    forensic veto pass. Names flunking earnings-quality are removed even if
    their surface score is highest — multi-signal alignment is the rule."""
    from src.screens.forensics import analyze as _forensic_analyze
    from src.screens.reverse_dcf import analyze as _reverse_dcf_analyze

    pool = []
    for c in qv_candidates:
        pool.append({**c, "_source": "Quality+Value"})
    for c in garp_candidates:
        pool.append({**c, "_source": "GARP"})
    if not pool:
        return None

    # Sort by surface score desc, then apply depth veto in order. First
    # name that survives is the focus pick. This avoids running forensics on
    # the whole pool unnecessarily.
    pool.sort(key=lambda x: x.get("score") or 0, reverse=True)
    for cand in pool:
        t = cand.get("ticker")
        if not t:
            continue
        try:
            fr = _forensic_analyze(t)
            if fr.fetched_ok and fr.composite_score is not None \
               and fr.composite_score >= FORENSIC_HARD_VETO:
                log.info("Focus veto %s: forensic %.1f (red)", t, fr.composite_score)
                continue
            cand["_forensic"] = {"score": fr.composite_score, "verdict": fr.verdict,
                                 "headline": fr.headline_flag} if fr.fetched_ok else None
        except Exception as exc:
            log.debug("focus-pick forensic %s failed: %s", t, exc)
            cand["_forensic"] = None
        try:
            dr = _reverse_dcf_analyze(t)
            if dr.fetched_ok and dr.implied_growth is not None:
                cand["_dcf"] = {
                    "verdict": dr.verdict,
                    "implied_growth_pct": round(dr.implied_growth * 100, 1),
                    "sales_cagr_5y_pct": (round(dr.historical_sales_cagr_5y * 100, 1)
                                          if dr.historical_sales_cagr_5y is not None else None),
                    "sector_ceiling_pct": (round(dr.sector_ceiling * 100, 0)
                                           if dr.sector_ceiling is not None else None),
                }
            else:
                cand["_dcf"] = {"verdict": dr.verdict, "note": dr.note} if dr.note else None
        except Exception as exc:
            log.debug("focus-pick dcf %s failed: %s", t, exc)
            cand["_dcf"] = None
        return cand  # first survivor wins
    return None


def render_chart_png(ticker: str, prices: Optional[PricesAdapter] = None) -> Optional[bytes]:
    """Render a 1-year price chart with 20/50/200 DMA → PNG bytes for PDF embed."""
    prices = prices or PricesAdapter()
    df = prices.history(f"{ticker}.NS", period="365d")
    if df.empty or len(df) < 30:
        return None
    df = df.copy()
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()

    fig, ax = plt.subplots(figsize=(8.5, 4), dpi=140)
    ax.plot(df.index, df["Close"], color="#0a3d62", linewidth=1.6, label="Close")
    ax.plot(df.index, df["SMA20"], color="#0a7e2f", linewidth=1.0,
            linestyle="--", label="20 DMA", alpha=0.7)
    ax.plot(df.index, df["SMA50"], color="#e0a800", linewidth=1.0,
            linestyle="--", label="50 DMA", alpha=0.7)
    ax.plot(df.index, df["SMA200"], color="#b71c1c", linewidth=1.0,
            label="200 DMA", alpha=0.7)
    ax.set_title(f"{ticker} — 1Y price action with 20/50/200 DMA",
                 fontsize=11, color="#1a1a1a")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=8)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def simple_dcf_range(fundamentals: Dict[str, Any]) -> Dict[str, Any]:
    """Very simple 3-scenario DCF based on supplied fundamentals.

    Inputs we have: P/E, profit_growth_3y, profit_growth_ttm, ROE.
    Output: bear / base / bull target prices, all relative-multiple-based.
    Not a full DCF — pragmatic ballpark for a one-pager."""
    pe = fundamentals.get("pe")
    profit_growth = fundamentals.get("profit_growth_3y") or 10
    current_price = fundamentals.get("current_price")
    if not pe or not current_price or pe <= 0:
        return {"error": "insufficient data for DCF range"}

    # Use forward EPS implied from PE and growth assumption
    ttm_eps = current_price / pe
    bear_growth = max(profit_growth * 0.5, 5)
    base_growth = profit_growth
    bull_growth = profit_growth * 1.3
    bear_pe = max(pe * 0.7, 10)
    base_pe = pe
    bull_pe = pe * 1.2

    bear_eps_fy26 = ttm_eps * (1 + bear_growth / 100)
    base_eps_fy26 = ttm_eps * (1 + base_growth / 100)
    bull_eps_fy26 = ttm_eps * (1 + bull_growth / 100)

    bear_tp = round(bear_eps_fy26 * bear_pe, 2)
    base_tp = round(base_eps_fy26 * base_pe, 2)
    bull_tp = round(bull_eps_fy26 * bull_pe, 2)

    return {
        "current": round(current_price, 2),
        "ttm_eps": round(ttm_eps, 2),
        "bear": {"eps_fy26": round(bear_eps_fy26, 2), "pe": round(bear_pe, 1),
                 "target": bear_tp,
                 "upside_pct": round((bear_tp / current_price - 1) * 100, 1)},
        "base": {"eps_fy26": round(base_eps_fy26, 2), "pe": round(base_pe, 1),
                 "target": base_tp,
                 "upside_pct": round((base_tp / current_price - 1) * 100, 1)},
        "bull": {"eps_fy26": round(bull_eps_fy26, 2), "pe": round(bull_pe, 1),
                 "target": bull_tp,
                 "upside_pct": round((bull_tp / current_price - 1) * 100, 1)},
        "method": ("Relative-multiple DCF approx: bear=0.5×growth at 0.7×PE, "
                   "base=current growth at current PE, bull=1.3×growth at 1.2×PE."),
    }


def render_markdown_block(focus: Dict[str, Any], fundamentals: Dict[str, Any],
                          dcf: Dict[str, Any], peers: Optional[List[Dict]] = None) -> str:
    """Markdown block for inclusion in morning brief or standalone view."""
    ticker = focus.get("ticker")
    name = fundamentals.get("name") or ticker
    source = focus.get("_source", "screen")
    lines = [
        f"## Stock in Focus — {name} ({ticker})",
        f"_Selected: top-scoring {source} candidate today (score {focus.get('score')}) "
        f"that cleared the earnings-quality / DCF veto._",
        "",
        "**Snapshot:**",
        f"- Price: ₹{fundamentals.get('current_price'):,.1f} · "
        f"Mkt cap: ₹{(fundamentals.get('market_cap_cr') or 0)/1000:.1f}k Cr · "
        f"P/E {fundamentals.get('pe')}",
        f"- ROCE {fundamentals.get('roce')}% · ROE {fundamentals.get('roe')}% · "
        f"D/E {fundamentals.get('debt_to_equity')} · Div yield "
        f"{fundamentals.get('dividend_yield')}%",
        f"- 3y profit CAGR {fundamentals.get('profit_growth_3y')}% · "
        f"3y sales CAGR {fundamentals.get('sales_growth_3y')}%",
        "",
    ]

    # Depth signals — forensic + reverse-DCF (set by pick_focus_ticker)
    forensic = focus.get("_forensic") or {}
    dcf_meta = focus.get("_dcf") or {}
    if forensic or dcf_meta:
        depth_bits = []
        if forensic.get("verdict"):
            badge = {"green":"🟢","amber":"🟠","red":"🔴"}.get(forensic["verdict"], "")
            depth_bits.append(
                f"Forensic {badge} **{forensic['verdict']}** "
                f"({forensic.get('score','—')}/100)"
                + (f" — {forensic['headline']}" if forensic.get("headline") else "")
            )
        if dcf_meta.get("verdict") and dcf_meta.get("implied_growth_pct") is not None:
            badge = {"cheap":"🟢","fair":"⚪","stretched":"🔴"}.get(dcf_meta["verdict"], "")
            ref_bits = []
            if dcf_meta.get("sales_cagr_5y_pct") is not None:
                ref_bits.append(f"5y CAGR {dcf_meta['sales_cagr_5y_pct']}%")
            if dcf_meta.get("sector_ceiling_pct") is not None:
                ref_bits.append(f"sector ceiling {int(dcf_meta['sector_ceiling_pct'])}%")
            ref_str = (", ".join(ref_bits))
            depth_bits.append(
                f"Reverse-DCF {badge} **{dcf_meta['verdict']}** — market-implied "
                f"growth **{dcf_meta['implied_growth_pct']}%**"
                + (f" vs {ref_str}" if ref_str else "")
            )
        if depth_bits:
            lines += ["**Depth signals:**"] + [f"- {b}" for b in depth_bits] + [""]
    if "error" not in dcf:
        lines += [
            "**Valuation range (relative-multiple approx):**",
            "",
            "| Scenario | EPS FY26E | P/E | Target | Upside |",
            "|---|---:|---:|---:|---:|",
            f"| Bear | {dcf['bear']['eps_fy26']} | {dcf['bear']['pe']} | "
            f"₹{dcf['bear']['target']:,} | {dcf['bear']['upside_pct']:+.1f}% |",
            f"| **Base** | **{dcf['base']['eps_fy26']}** | **{dcf['base']['pe']}** | "
            f"**₹{dcf['base']['target']:,}** | **{dcf['base']['upside_pct']:+.1f}%** |",
            f"| Bull | {dcf['bull']['eps_fy26']} | {dcf['bull']['pe']} | "
            f"₹{dcf['bull']['target']:,} | {dcf['bull']['upside_pct']:+.1f}% |",
            "",
            f"_{dcf['method']}_",
            "",
        ]
    return "\n".join(lines)


def build_focus(qv_candidates: List[Dict], garp_candidates: List[Dict],
                screener: Optional[ScreenerAdapter] = None) -> Dict[str, Any]:
    """Return the full stock-in-focus payload for morning brief composition."""
    screener = screener or ScreenerAdapter()
    pick = pick_focus_ticker(qv_candidates, garp_candidates)
    if not pick:
        return {"error": "no candidates"}
    ticker = pick.get("ticker")
    try:
        fundamentals = screener.fundamentals(ticker)
    except Exception as exc:
        return {"error": f"fundamentals fetch failed: {exc}"}

    dcf = simple_dcf_range(fundamentals)
    md = render_markdown_block(pick, fundamentals, dcf)
    chart_png = render_chart_png(ticker)

    return {
        "ticker": ticker,
        "fundamentals": fundamentals,
        "dcf": dcf,
        "markdown": md,
        "chart_png": chart_png,
        "source": pick.get("_source"),
        "score": pick.get("score"),
    }
