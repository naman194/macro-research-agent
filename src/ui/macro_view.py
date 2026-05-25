"""Macro heatmap — global indicators across major economies."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.data.fred import FredAdapter
from src.data.imf import IMFAdapter
from src.data.worldbank import WorldBankAdapter


@st.cache_data(ttl=3600)
def _imf_table() -> pd.DataFrame:
    return IMFAdapter().latest_table()


@st.cache_data(ttl=3600)
def _wb_table() -> pd.DataFrame:
    return WorldBankAdapter().latest_table()


@st.cache_data(ttl=3600)
def _fred_snapshot() -> pd.DataFrame:
    return FredAdapter().snapshot()


def render() -> None:
    st.header("Macro Snapshot")
    st.caption("Top-down view across major economies. Refresh weekly.")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("IMF WEO — by country")
        try:
            imf = _imf_table()
        except Exception as exc:
            st.error(f"IMF fetch failed: {exc}")
            imf = pd.DataFrame()
        if imf.empty:
            st.info("No IMF data returned.")
        else:
            display_cols = [c for c in imf.columns if not c.endswith("_year")]
            st.dataframe(imf[display_cols], width="stretch", hide_index=True)

    with col2:
        st.subheader("World Bank — structural")
        try:
            wb = _wb_table()
        except Exception as exc:
            st.error(f"World Bank fetch failed: {exc}")
            wb = pd.DataFrame()
        if wb.empty:
            st.info("No World Bank data returned.")
        else:
            display_cols = [c for c in wb.columns if not c.endswith("_year")]
            st.dataframe(wb[display_cols], width="stretch", hide_index=True)

    st.subheader("US macro (FRED) — drives EM risk-on/off")
    fred = _fred_snapshot()
    if fred.empty or fred["latest"].isna().all():
        st.warning(
            "FRED_API_KEY missing or no data. Add a free key from "
            "fred.stlouisfed.org to enable this panel."
        )
    else:
        st.dataframe(fred, width="stretch", hide_index=True)

    # GDP growth bar chart from IMF latest
    if not imf.empty and "GDP_RGROWTH" in imf.columns:
        st.subheader("Real GDP growth — latest IMF estimates")
        chart_df = imf.dropna(subset=["GDP_RGROWTH"]).sort_values("GDP_RGROWTH", ascending=True)
        fig = px.bar(
            chart_df, x="GDP_RGROWTH", y="country", orientation="h",
            labels={"GDP_RGROWTH": "Real GDP growth (% YoY)", "country": ""},
            color="GDP_RGROWTH", color_continuous_scale="RdYlGn",
        )
        fig.update_layout(height=420, coloraxis_showscale=False)
        st.plotly_chart(fig, width="stretch")
