"""F&O Analytics view — PCR, max pain, OI-based support/resistance."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data.fno import DEFAULT_FNO_INDICES, DEFAULT_FNO_STOCKS, FnoAdapter


@st.cache_data(ttl=900, show_spinner="Pulling option chains for indices…")
def _index_signals():
    return FnoAdapter().headline_signals()


@st.cache_data(ttl=900, show_spinner=False)
def _stock_analytics(symbol: str):
    return FnoAdapter().analytics(symbol)


@st.cache_data(ttl=900, show_spinner=False)
def _chain(symbol: str, strikes: int):
    return FnoAdapter().chain_table(symbol, strikes_around=strikes)


def _sentiment_color(label: str) -> str:
    if "bullish" in (label or "").lower(): return "🟢"
    if "bearish" in (label or "").lower(): return "🔴"
    return "🟡"


def render() -> None:
    st.header("F&O / Open Interest Analytics")
    st.caption(
        "PCR (put-call ratio by OI), Max Pain, highest-OI strike-based support & resistance. "
        "PCR > 1.3 = heavy put writing (bullish); < 0.7 = heavy call writing (bearish). "
        "Max Pain is the gravitational price for expiry."
    )

    st.subheader("Index F&O Snapshot")
    rows = _index_signals()
    if rows:
        df = pd.DataFrame(rows)
        df["💡"] = df["sentiment"].apply(_sentiment_color)
        st.dataframe(
            df[["💡", "symbol", "expiry", "underlying", "pcr_oi", "max_pain",
                "max_pain_distance_pct", "support", "resistance", "sentiment"]],
            width="stretch", hide_index=True,
            column_config={
                "underlying": st.column_config.NumberColumn("Spot", format="%.0f"),
                "pcr_oi": st.column_config.NumberColumn("PCR", format="%.2f"),
                "max_pain": st.column_config.NumberColumn("Max Pain", format="%.0f"),
                "max_pain_distance_pct": st.column_config.NumberColumn("% from spot", format="%.2f"),
                "support": st.column_config.NumberColumn("Support", format="%.0f"),
                "resistance": st.column_config.NumberColumn("Resistance", format="%.0f"),
            },
        )
    else:
        st.warning("Could not fetch index F&O data — NSE may be throttling.")

    st.markdown("---")
    st.subheader("Drill-down — Option Chain & Analytics")

    c1, c2 = st.columns([2, 1])
    options = DEFAULT_FNO_INDICES + DEFAULT_FNO_STOCKS
    symbol = c1.selectbox("Symbol", options, index=0)
    custom = c1.text_input("…or enter NSE F&O symbol manually (e.g. RELIANCE)").strip().upper()
    target = custom or symbol
    strikes = c2.slider("Strikes around ATM", 5, 25, 10)

    if target:
        a = _stock_analytics(target)
        if "error" in a:
            st.error(f"Could not get F&O data for {target}: {a['error']}")
        else:
            cols = st.columns(4)
            cols[0].metric("Spot", f"{a['underlying']:.0f}" if a['underlying'] else "n/a")
            cols[1].metric("PCR (OI)", f"{a['pcr_oi']:.2f}" if a['pcr_oi'] else "n/a")
            mp_d = a.get('max_pain_distance_pct')
            cols[2].metric(
                "Max Pain", f"{a['max_pain_strike']:.0f}",
                delta=f"{mp_d:+.2f}% vs spot" if mp_d is not None else None
            )
            cols[3].metric("Sentiment", a.get("sentiment", "n/a"))

            c1, c2 = st.columns(2)
            c1.metric("Support (max PE OI)", f"{a['support_strike']:.0f}",
                      delta=f"OI {a['support_oi']:,}")
            c2.metric("Resistance (max CE OI)", f"{a['resistance_strike']:.0f}",
                      delta=f"OI {a['resistance_oi']:,}")

            df = _chain(target, strikes)
            if not df.empty:
                st.subheader("Option Chain (centered on ATM)")
                st.dataframe(df, width="stretch", hide_index=True)
            else:
                st.info("Option chain table unavailable.")
