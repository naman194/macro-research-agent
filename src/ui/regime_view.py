"""Regime + Relative Strength — the trend half of the workbench."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import DEFAULT_UNIVERSE
from src.screens.regime import (
    REGIME_WEIGHTS,
    WINDOW_DAYS,
    regime_report,
    relative_strength_table,
)
from src.ui.components import depth_signal_tile, page_header


LABEL_BADGE = {"risk_on": "🟢", "neutral": "⚪", "risk_off": "🔴"}


@st.cache_data(ttl=3600, show_spinner=False)
def _regime() -> dict:
    r = regime_report()
    return {
        "composite_score": r.composite_score,
        "label": r.label,
        "components": r.components,
        "notes": r.notes,
    }


@st.cache_data(ttl=21600, show_spinner=False)
def _rs(universe: tuple) -> pd.DataFrame:
    return relative_strength_table(list(universe))


def render() -> None:
    page_header(
        "Regime + Relative Strength",
        "Where is the Indian equity market right now — risk-on, neutral, or risk-off? "
        "Which names are *leading* the index across multiple windows?",
    )

    with st.spinner("Computing regime composite + sector breadth…"):
        r = _regime()

    badge = LABEL_BADGE.get(r["label"], "⚪")
    st.markdown(
        f"### {badge} Composite regime score: **{r['composite_score']}** / 100 "
        f"· label **{r['label'].replace('_',' ')}**"
    )

    # Components in 5 tiles
    cols = st.columns(5)
    comps = r["components"]
    notes = r["notes"]
    labels = ["Nifty trend", "FII/DII flows", "Sector breadth", "USD/INR", "Brent"]
    keys = ["nifty_trend", "flows", "sector_breadth", "inr", "brent"]
    for col, label, k, note in zip(cols, labels, keys, notes):
        score = comps.get(k, 50)
        verdict = ("green" if score >= 60 else ("red" if score <= 40 else "amber"))
        with col:
            depth_signal_tile(
                label=label,
                value=f"{score:.0f}/100",
                verdict=verdict,
                note=note[:80] + ("…" if len(note) > 80 else ""),
            )

    with st.expander("Methodology + weights"):
        st.json({k: f"{v*100:.0f}%" for k, v in REGIME_WEIGHTS.items()})
        st.caption(
            "Every component is a 0-100 sub-score. Final composite = weighted "
            "average. Labels: ≥ 60 risk-on, 40-60 neutral, ≤ 40 risk-off."
        )

    st.markdown("---")

    # ============================================================
    # Relative strength
    # ============================================================

    st.markdown("##### Relative Strength — leaders vs Nifty (1M / 3M / 6M / 12M)")
    universes = {
        "NIFTY 50 core":              DEFAULT_UNIVERSE[:50],
        "NIFTY 100 + Next 50 (~100)": DEFAULT_UNIVERSE[:100],
        "Full default universe":      DEFAULT_UNIVERSE,
    }
    choice = st.selectbox("Universe", list(universes.keys()), index=0)
    universe = universes[choice]
    st.caption(
        f"Scanning **{len(universe)} names**. Cached 6h. RS = stock %-return − "
        "Nifty %-return over each window."
    )

    with st.spinner("Computing relative strength table…"):
        df = _rs(tuple(universe))

    if df.empty:
        st.warning("No relative-strength data returned. yfinance may be throttling.")
        return

    # Filter: top leaders / bottom laggards toggle
    c1, c2 = st.columns(2)
    show_leaders = c1.checkbox("Leaders only (RS_3M > 0)", value=True)
    n_show = c2.number_input("Show top N", min_value=10, max_value=200, value=30)

    table = df.copy()
    if show_leaders:
        table = table[table["RS_3M"].fillna(-9999) > 0]
    table = table.head(int(n_show))

    # Style: green for positive, red for negative
    def _color(v):
        if v is None or pd.isna(v): return ""
        if v > 5:  return "background-color:#d9f5e3"
        if v > 0:  return "background-color:#eaf7f0"
        if v < -5: return "background-color:#fbe1e1"
        if v < 0:  return "background-color:#f7eaea"
        return ""

    rs_cols = [f"RS_{w}" for w in WINDOW_DAYS.keys()]
    styled = table.style.applymap(_color, subset=rs_cols).format("{:+.1f}", subset=rs_cols, na_rep="—")
    st.dataframe(styled, width="stretch")

    st.caption(
        "Reading the table: **RS_3M > 0** means the stock outperformed Nifty over "
        "the last quarter. A name leading on all four windows is a structural "
        "outperformer; one leading short-term but lagging 12M may be a regime change."
    )
