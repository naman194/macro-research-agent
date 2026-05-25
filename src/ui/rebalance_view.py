"""Index Rebalance Predictor view."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data.index_rebalance import IndexRebalanceAdapter


@st.cache_data(ttl=24 * 3600, show_spinner="Computing rebalance predictions…")
def _predict():
    return IndexRebalanceAdapter().predict_nifty50_changes()


def render() -> None:
    st.header("Index Rebalance Predictor — Nifty 50")
    st.caption("Likely add/drop candidates based on free-float market-cap ranking. "
               "NSE rebalances Nifty 50 semi-annually (Jan + Jul cut-off, implementation "
               "last Friday of Mar/Sep).")

    res = _predict()
    if "error" in res:
        st.error(res["error"])
        return

    st.info(f"Next rebalance: {res['next_rebalance']}")

    with st.expander("Methodology", expanded=False):
        st.write(res["methodology"])

    adds = pd.DataFrame(res.get("likely_additions", []))
    dels = pd.DataFrame(res.get("likely_deletions", []))

    st.subheader("🟢 Likely Additions")
    st.caption("Non-Nifty-50 members ranked in the top 50 by market cap — most likely to "
               "be inducted at next review. Passive inflow estimated using ~Rs 3.5L Cr "
               "of Nifty 50 tracking AUM.")
    if adds.empty:
        st.info("No clear addition candidates above the cut-off.")
    else:
        st.dataframe(
            adds[["rank", "ticker", "name", "market_cap_cr", "est_weight_pct",
                  "est_passive_inflow_cr", "current_price", "pe"]],
            width="stretch", hide_index=True,
            column_config={
                "market_cap_cr": st.column_config.NumberColumn("Mkt cap (Cr)", format="%.0f"),
                "est_weight_pct": st.column_config.NumberColumn("Est weight %", format="%.2f"),
                "est_passive_inflow_cr": st.column_config.NumberColumn(
                    "Est inflow (Cr)", format="%.0f"),
            },
        )

    st.subheader("🔴 Likely Deletions")
    st.caption("Current Nifty 50 members ranked below 55 — vulnerable to exclusion. "
               "Passive outflow estimated on same basis.")
    if dels.empty:
        st.info("All current Nifty 50 members are safely in the top 55.")
    else:
        st.dataframe(
            dels[["rank", "ticker", "name", "market_cap_cr", "est_weight_pct",
                  "est_passive_outflow_cr", "current_price", "pe"]],
            width="stretch", hide_index=True,
            column_config={
                "market_cap_cr": st.column_config.NumberColumn("Mkt cap (Cr)", format="%.0f"),
                "est_weight_pct": st.column_config.NumberColumn("Est weight %", format="%.2f"),
                "est_passive_outflow_cr": st.column_config.NumberColumn(
                    "Est outflow (Cr)", format="%.0f"),
            },
        )

    with st.expander("Full universe ranking (Nifty 50 + Next 50)", expanded=False):
        full = pd.DataFrame(res.get("full_ranking", []))
        st.dataframe(full, width="stretch", hide_index=True)
