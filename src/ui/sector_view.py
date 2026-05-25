"""Sector dashboards — Banks, IT, Auto with sector-specific KPIs."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data.sector_kpis import AUTO_UNIVERSE, BANK_UNIVERSE, IT_UNIVERSE, SectorAdapter


@st.cache_data(ttl=3600, show_spinner="Loading banks KPIs…")
def _banks(): return SectorAdapter().banks().to_dict("records")


@st.cache_data(ttl=3600, show_spinner="Loading IT KPIs (incl. USDINR sensitivity)…")
def _it(): return SectorAdapter().it().to_dict("records")


@st.cache_data(ttl=3600, show_spinner="Loading auto KPIs…")
def _auto(): return SectorAdapter().auto().to_dict("records")


def render() -> None:
    st.header("Sector Dashboards")
    st.caption("Sector-tailored KPIs from quarterly results. Three sectors in Phase 1; "
               "more coming in Phase 4.")

    tabs = st.tabs(["Banks", "IT Services", "Auto"])

    with tabs[0]:
        st.caption(f"Coverage: {len(BANK_UNIVERSE)} private + PSU banks. "
                   "Showing latest quarter — revenue, net profit, financing margin, P/B.")
        df = pd.DataFrame(_banks())
        if df.empty:
            st.warning("Banks data unavailable.")
        else:
            cols = ["ticker", "name", "latest_period", "revenue_cr", "revenue_yoy_pct",
                    "revenue_qoq_pct", "net_profit_cr", "net_profit_yoy_pct",
                    "operating_profit_cr", "opm_pct", "financing_margin_pct",
                    "pe", "roe_pct", "market_cap_cr"]
            existing = [c for c in cols if c in df.columns]
            st.dataframe(df[existing], width="stretch", hide_index=True,
                         column_config={
                             "revenue_yoy_pct": st.column_config.NumberColumn("Rev YoY %", format="%.1f"),
                             "revenue_qoq_pct": st.column_config.NumberColumn("Rev QoQ %", format="%.1f"),
                             "net_profit_yoy_pct": st.column_config.NumberColumn("NP YoY %", format="%.1f"),
                         })

    with tabs[1]:
        st.caption(f"Coverage: {len(IT_UNIVERSE)} large/mid-cap IT services. "
                   "Includes 90d return correlation with USDINR — negative correlation "
                   "= names that fall when INR weakens (counter-intuitive but common in risk-off).")
        df = pd.DataFrame(_it())
        if df.empty:
            st.warning("IT data unavailable.")
        else:
            cols = ["ticker", "name", "latest_period", "revenue_cr", "revenue_yoy_pct",
                    "revenue_qoq_pct", "opm_pct", "net_profit_yoy_pct",
                    "usdinr_correlation_90d", "pe", "roe", "market_cap_cr"]
            existing = [c for c in cols if c in df.columns]
            st.dataframe(df[existing], width="stretch", hide_index=True,
                         column_config={
                             "revenue_yoy_pct": st.column_config.NumberColumn("Rev YoY %", format="%.1f"),
                             "opm_pct": st.column_config.NumberColumn("OPM %", format="%.1f"),
                             "usdinr_correlation_90d": st.column_config.NumberColumn(
                                 "USDINR corr (90d)", format="%.2f"),
                         })

    with tabs[2]:
        st.caption(f"Coverage: {len(AUTO_UNIVERSE)} auto OEMs + ancillaries. "
                   "Monthly sales data lives in corporate announcements — see Catalysts view.")
        df = pd.DataFrame(_auto())
        if df.empty:
            st.warning("Auto data unavailable.")
        else:
            cols = ["ticker", "name", "latest_period", "revenue_cr", "revenue_yoy_pct",
                    "revenue_qoq_pct", "opm_pct", "net_profit_yoy_pct",
                    "roce", "roe", "pe", "debt_to_equity", "market_cap_cr"]
            existing = [c for c in cols if c in df.columns]
            st.dataframe(df[existing], width="stretch", hide_index=True,
                         column_config={
                             "revenue_yoy_pct": st.column_config.NumberColumn("Rev YoY %", format="%.1f"),
                             "opm_pct": st.column_config.NumberColumn("OPM %", format="%.1f"),
                         })
