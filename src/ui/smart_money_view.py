"""Smart Money view — block/bulk deals + insider/promoter activity in one place."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data.deals import DealsAdapter
from src.data.insider import InsiderAdapter


@st.cache_data(ttl=21600, show_spinner="Pulling bulk + block deals…")
def _deals():
    a = DealsAdapter()
    return {"bulk": a.bulk_deals().to_dict("records"),
            "block": a.block_deals().to_dict("records")}


@st.cache_data(ttl=21600, show_spinner="Pulling insider disclosures…")
def _insider(days: int):
    return InsiderAdapter().latest_summary(days_back=days, top_n=20)


def _value_color(val):
    if val is None:
        return ""
    try:
        if val > 0:
            return "color:#0a7e2f"
        if val < 0:
            return "color:#b71c1c"
    except Exception:
        pass
    return ""


def render() -> None:
    st.header("Smart Money")
    st.caption(
        "Where institutional money actually moved yesterday — block deals (cleared via "
        "the negotiated window), bulk deals (>0.5% of float), and SEBI PIT insider/promoter "
        "disclosures. Highest-conviction internal signals."
    )

    tab_block, tab_bulk, tab_insider = st.tabs(["Block Deals", "Bulk Deals", "Insider / Promoter"])

    d = _deals()

    with tab_block:
        st.caption("Block deals — large institutional prints in the negotiated window. "
                   "These are typically cleaner reads on positioning.")
        block = pd.DataFrame(d["block"])
        if block.empty:
            st.info("No block deals in current NSE archive.")
        else:
            st.dataframe(
                block[["date", "symbol", "security", "client", "side", "qty", "price", "value_cr"]]
                    .sort_values("value_cr", ascending=False),
                width="stretch", hide_index=True,
            )

    with tab_bulk:
        st.caption("Bulk deals — transactions ≥ 0.5% of company's listed shares. "
                   "Institutional flag = MF/Insurance/FII/AIF/Pension/PMS in counterparty name.")
        bulk = pd.DataFrame(d["bulk"])
        if bulk.empty:
            st.info("No bulk deals in current NSE archive.")
        else:
            c1, c2 = st.columns(2)
            side_filter = c1.selectbox("Side", ["All", "BUY", "SELL"])
            inst_only = c2.checkbox("Institutional counterparty only", value=False)
            f = bulk.copy()
            if side_filter != "All":
                f = f[f["side"].str.upper() == side_filter]
            if inst_only and "institutional" in f.columns:
                f = f[f["institutional"]]
            st.dataframe(
                f[["date", "symbol", "security", "client", "side",
                   "qty", "price", "value_cr", "institutional"]]
                    .sort_values("value_cr", ascending=False),
                width="stretch", hide_index=True,
            )

    with tab_insider:
        st.caption("SEBI PIT disclosures — promoter buys are the highest signal. "
                   "ESOP transactions are excluded (noise).")
        days = st.slider("Lookback window (days)", 14, 90, 30)
        s = _insider(days)
        st.write(f"**{s['total']} total disclosures · as of {s.get('as_of', 'n/a')}**")

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Promoter Buys 🟢")
            st.caption("Most-watched signal on the desk.")
            if s["promoter_buys"]:
                df = pd.DataFrame(s["promoter_buys"])
                st.dataframe(df[["date", "symbol", "company", "acq_name",
                                "qty", "buy_value_cr", "txn_type"]],
                             width="stretch", hide_index=True)
            else:
                st.info("No promoter buys in window.")
        with c2:
            st.subheader("Promoter Sells 🔴")
            if s["promoter_sells"]:
                df = pd.DataFrame(s["promoter_sells"])
                st.dataframe(df[["date", "symbol", "company", "acq_name",
                                "qty", "sell_value_cr", "txn_type"]],
                             width="stretch", hide_index=True)
            else:
                st.info("No promoter sells in window.")

        st.subheader("Other Insider Activity (KMP, designated persons)")
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Buys**")
            if s["other_buys"]:
                df = pd.DataFrame(s["other_buys"])
                st.dataframe(df[["date", "symbol", "acq_name", "qty", "buy_value_cr"]],
                             width="stretch", hide_index=True)
        with c2:
            st.write("**Sells**")
            if s["other_sells"]:
                df = pd.DataFrame(s["other_sells"])
                st.dataframe(df[["date", "symbol", "acq_name", "qty", "sell_value_cr"]],
                             width="stretch", hide_index=True)

        if s["pledges"]:
            st.subheader("Pledge Activity ⚠")
            st.caption("Promoter pledging stock — watch for stress signals.")
            df = pd.DataFrame(s["pledges"])
            st.dataframe(df[["date", "symbol", "acq_name", "qty", "txn_type"]],
                         width="stretch", hide_index=True)
