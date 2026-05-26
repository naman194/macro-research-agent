"""Screener output — ranked ideas with filters."""
from __future__ import annotations

from typing import List

import pandas as pd
import streamlit as st

from src.config import DEFAULT_UNIVERSE
from src.screens.quality_value import QualityValueScreener
from src.ui.components import page_header


@st.cache_data(ttl=3600, show_spinner="Running screener…")
def _run_qv(universe: tuple) -> dict:
    res = QualityValueScreener().run(list(universe))
    return {
        "candidates": res.candidates.to_dict("records"),
        "criteria": res.criteria,
        "rejected_count": res.rejected_count,
        "notes": res.notes,
    }


def render() -> None:
    page_header(
        "Quality + Value screen",
        "Buffett-flavoured filter — ROCE/ROE thresholds, low debt, consistent growth. "
        "Universe defaults to a curated ~150-name subset of NIFTY 500. Composite score "
        "incorporates structural risk/catalyst overlay.",
    )

    with st.expander("Screening criteria", expanded=False):
        res_meta = _run_qv(tuple(DEFAULT_UNIVERSE))
        crit = res_meta["criteria"]
        st.json(crit)
        st.write("**Notes:**")
        for n in res_meta["notes"]:
            st.write(f"- {n}")
        st.write(f"**Rejected (failed hard filters):** {res_meta['rejected_count']}")

    cands = pd.DataFrame(res_meta["candidates"])
    if cands.empty:
        st.warning("No candidates passed the screen. screener.in may be rate-limiting; "
                   "try again in a few minutes.")
        return

    # Filters
    col1, col2, col3 = st.columns(3)
    sectors = ["All"] + sorted(
        cands["sector"].dropna().unique().tolist()
    )
    sector_sel = col1.selectbox("Sector", sectors)
    min_mcap = col2.number_input(
        "Min mkt cap (Cr)", min_value=0, value=1000, step=500
    )
    min_score = col3.slider("Min composite score", 0, 100, 30)

    filtered = cands.copy()
    if sector_sel != "All":
        filtered = filtered[filtered["sector"] == sector_sel]
    filtered = filtered[filtered["market_cap_cr"].fillna(0) >= min_mcap]
    filtered = filtered[filtered["score"] >= min_score]

    st.write(f"**{len(filtered)} ideas** match filters")
    st.dataframe(
        filtered[[
            "ticker", "name", "sector", "score",
            "quality_sub", "value_sub", "growth_sub",
            "roce", "roe", "debt_to_equity", "pe", "dividend_yield",
            "market_cap_cr", "sales_growth_3y", "profit_growth_3y",
        ]],
        width="stretch",
        hide_index=True,
    )

    # Store top tickers in session for the research note view
    st.session_state["last_screen_tickers"] = filtered["ticker"].tolist()
