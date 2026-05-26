"""Forensics view — earnings quality + accounting drift screen.

Two modes:
  1. Universe scan — composite ForensicRiskScore across DEFAULT_UNIVERSE,
     sortable, with verdict traffic lights. Use to spot the top risk names
     overnight (or after each results season).
  2. Single-name deep dive — all nine metrics with time-series sparklines
     and verdict notes per metric. The "open the annual report" decision aid.
"""
from __future__ import annotations

from typing import List

import pandas as pd
import streamlit as st

from src.config import DEFAULT_UNIVERSE
from src.screens.forensics import (
    ALL_METRICS,
    ForensicsScreener,
    analyze,
)
from src.ui.components import cross_link_buttons


VERDICT_EMOJI = {"red": "🔴", "amber": "🟠", "green": "🟢", "na": "⚪"}

METRIC_LABELS = {
    "cash_conv":       "Cash conversion (CFO/PAT)",
    "sloan_accruals":  "Sloan accruals ((NI-CFO)/avg TA)",
    "wc_drift":        "Working-capital drift",
    "beneish_sgi":     "Beneish SGI (sales growth)",
    "beneish_depi":    "Beneish DEPI (depr slowdown)",
    "debt_divergence": "Debt vs profit CAGR",
    "int_cover":       "Interest coverage",
    "oi_share":        "Other income / PBT",
    "lvgi":            "Beneish LVGI (leverage spike)",
}


# ============================================================
# Cached runners
# ============================================================

@st.cache_data(ttl=86_400, show_spinner=False)
def _run_universe(universe: tuple) -> dict:
    """Run forensics across a universe. Cached for 24h (heavy)."""
    res = ForensicsScreener().run(list(universe))
    return {
        "candidates": res.candidates.to_dict("records"),
        "criteria": res.criteria,
        "rejected_count": res.rejected_count,
        "notes": res.notes,
    }


@st.cache_data(ttl=86_400, show_spinner=False)
def _run_single(ticker: str) -> dict:
    """Run forensics on one ticker. Used by deep-dive."""
    r = analyze(ticker)
    return {
        "ticker": r.ticker,
        "composite_score": r.composite_score,
        "verdict": r.verdict,
        "headline_flag": r.headline_flag,
        "fetched_ok": r.fetched_ok,
        "metrics": {
            name: {
                "latest": m.latest,
                "score": m.score,
                "verdict": m.verdict,
                "note": m.note,
                "series": m.series.to_dict() if m.series is not None else {},
            }
            for name, m in r.metrics.items()
        },
    }


# ============================================================
# Render
# ============================================================

def render() -> None:
    st.header("Forensics — earnings quality + accounting drift")
    st.caption(
        "Nine forensic indicators across 5-10 years of fundamentals. "
        "Composite **ForensicRiskScore** is a *prior* (where to look harder) — "
        "not a verdict. Red names ≠ frauds; they're names where the annual "
        "report deserves a closer read before any action."
    )

    mode = st.radio(
        "Mode",
        ["Universe scan", "Single-name deep dive"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if mode == "Universe scan":
        _render_universe()
    else:
        _render_single()


def _render_universe() -> None:
    universes = {
        "NIFTY 50 core (first 50)":  DEFAULT_UNIVERSE[:50],
        "NIFTY 100 + Next 50 (~100)": DEFAULT_UNIVERSE[:100],
        "Full default universe (~150)": DEFAULT_UNIVERSE,
    }
    choice = st.selectbox("Universe", list(universes.keys()), index=0)
    universe = universes[choice]

    st.caption(
        f"Scanning **{len(universe)} names**. First run is slow (one HTTP per "
        "name, ~6-15s/name); cached 24h thereafter."
    )

    with st.spinner(f"Scanning {len(universe)} names…"):
        meta = _run_universe(tuple(universe))

    with st.expander("Methodology", expanded=False):
        st.json(meta["criteria"])
        for n in meta["notes"]:
            st.write(f"- {n}")
        st.write(f"**Failed fetch:** {meta['rejected_count']}")

    cands = pd.DataFrame(meta["candidates"])
    if cands.empty:
        st.warning("No data returned. screener.in may be throttling; retry later.")
        return

    # Filter controls
    col1, col2 = st.columns(2)
    verdict_filter = col1.multiselect(
        "Verdict", ["red", "amber", "green"], default=["red", "amber"]
    )
    min_score = col2.slider("Min composite score", 0, 100, 30)

    filtered = cands.copy()
    if verdict_filter:
        filtered = filtered[filtered["verdict"].isin(verdict_filter)]
    filtered = filtered[filtered["composite_score"] >= min_score]

    st.write(f"**{len(filtered)} names** match filters")

    # Display table — verdict emoji + composite + headline + per-metric mini-cells
    if filtered.empty:
        return

    display = filtered.copy()
    display["verdict"] = display["verdict"].map(VERDICT_EMOJI).fillna("⚪")
    # Compact per-metric verdict columns
    for name in ALL_METRICS:
        col = f"{name}_verdict"
        if col in display.columns:
            display[name] = display[col].map(VERDICT_EMOJI).fillna("⚪")

    cols_to_show = ["ticker", "verdict", "composite_score", "headline_flag"] + ALL_METRICS
    st.dataframe(
        display[cols_to_show].rename(columns={"verdict": "✓", "composite_score": "score",
                                              "headline_flag": "headline finding"}),
        width="stretch",
        hide_index=True,
    )

    # Click-through aid: store top reds for deep-dive
    reds = filtered[filtered["verdict"].isin(["red", "amber"])]["ticker"].tolist() \
        if "verdict" in filtered.columns else []
    if reds:
        st.caption(f"💡 Top names to deep-dive: {', '.join(reds[:10])}")


def _render_single() -> None:
    col1, col2 = st.columns([1, 3])
    universe_options = sorted(DEFAULT_UNIVERSE)
    # Prefer the cross-view active ticker if set; otherwise default to INFY
    carried = st.session_state.get("active_ticker")
    default_idx = universe_options.index(carried) if carried in universe_options \
        else universe_options.index("INFY")
    ticker = col1.selectbox("Ticker", universe_options, index=default_idx)
    custom = col2.text_input(
        "…or any NSE symbol",
        value=(carried if carried and carried not in universe_options else ""),
        placeholder="e.g. POLYCAB",
    ).strip().upper()
    if custom:
        ticker = custom

    if not ticker:
        return

    with st.spinner(f"Analyzing {ticker}…"):
        rep = _run_single(ticker)

    if not rep["fetched_ok"]:
        st.error(f"Could not fetch fundamentals for {ticker}. The ticker may not "
                 "exist on screener.in or its slug differs (check `SCREENER_SLUG_OVERRIDES` in config).")
        return

    # Header banner
    verdict = rep["verdict"]
    score = rep["composite_score"]
    badge = VERDICT_EMOJI.get(verdict, "⚪")
    st.markdown(f"### {badge} **{ticker}** — ForensicRiskScore **{score}** / 100 ({verdict})")
    if rep["headline_flag"]:
        st.warning(f"⚠ Top finding: {rep['headline_flag']}")

    # Metrics grid — 3 columns, one panel per metric
    cols = st.columns(3)
    for i, name in enumerate(ALL_METRICS):
        m = rep["metrics"].get(name) or {}
        with cols[i % 3]:
            v = m.get("verdict", "na")
            badge_m = VERDICT_EMOJI.get(v, "⚪")
            st.markdown(f"**{badge_m} {METRIC_LABELS[name]}**")
            st.caption(m.get("note", "—"))
            series = m.get("series") or {}
            if series:
                df = pd.DataFrame({"value": series.values()}, index=list(series.keys()))
                # Single-row charts are noisy; only show if 3+ points
                if len(df) >= 3:
                    st.line_chart(df, height=120)
                else:
                    st.write(df)
            st.markdown("&nbsp;", unsafe_allow_html=True)  # spacer

    # Carry this ticker as the active context for cross-view navigation
    st.session_state["active_ticker"] = ticker
    st.markdown("---")
    st.caption("Open this ticker in another view:")
    cross_link_buttons(ticker, current_view="🔬 Forensics")
