"""GARP (Growth at Reasonable Price) screener view."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import DEFAULT_UNIVERSE
from src.screens.garp import GARPScreener
from src.ui.components import page_header


@st.cache_data(ttl=3600, show_spinner="Running GARP screen…")
def _run(universe: tuple) -> dict:
    res = GARPScreener().run(list(universe))
    return {
        "candidates": res.candidates.to_dict("records"),
        "criteria": res.criteria,
        "rejected_count": res.rejected_count,
        "notes": res.notes,
    }


def render() -> None:
    page_header(
        "GARP — Growth at Reasonable Price",
        "Lynch/Lipper-style: cheap (PEG ≤ 1.5) but growing (3y profit ≥ 12%).",
    )

    meta = _run(tuple(DEFAULT_UNIVERSE))

    with st.expander("Screening criteria", expanded=False):
        st.json(meta["criteria"])
        st.write(f"**Rejected (failed hard filters):** {meta['rejected_count']}")
        for n in meta["notes"]:
            st.write(f"- {n}")

    cands = pd.DataFrame(meta["candidates"])
    if cands.empty:
        st.warning("No candidates passed the GARP screen on the current universe.")
        return

    c1, c2, c3 = st.columns(3)
    max_peg = c1.slider("Max PEG", 0.1, 1.5, 1.5, 0.1)
    min_growth = c2.slider("Min 3y profit growth %", 12, 60, 12)
    min_score = c3.slider("Min composite score", 0, 100, 25)

    f = cands.copy()
    f = f[f["peg"].fillna(99) <= max_peg]
    f = f[f["profit_growth_3y"].fillna(0) >= min_growth]
    f = f[f["score"] >= min_score]

    st.write(f"**{len(f)} GARP ideas** match filters")
    st.dataframe(
        f[["ticker", "name", "sector", "score", "peg",
           "growth_sub", "price_sub", "quality_sub", "momentum_sub",
           "pe", "profit_growth_3y", "profit_growth_ttm", "sales_growth_3y",
           "roe", "roce", "debt_to_equity", "market_cap_cr", "price_cagr_1y"]],
        width="stretch", hide_index=True,
    )

    st.session_state["last_screen_tickers"] = f["ticker"].tolist()
