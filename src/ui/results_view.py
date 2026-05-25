"""Results view — quarterly results history + this-week's results calendar."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data.screener import ScreenerAdapter
from src.screens.special_situations import NSEEventsAdapter


@st.cache_data(ttl=1800, show_spinner=False)
def _quarterly(ticker: str):
    return ScreenerAdapter().quarterly_results(ticker)


@st.cache_data(ttl=1800, show_spinner=False)
def _shareholding(ticker: str):
    return ScreenerAdapter().shareholding(ticker)


@st.cache_data(ttl=21600, show_spinner="Pulling NSE events calendar…")
def _calendar():
    df = NSEEventsAdapter().all_events()
    if df.empty:
        return []
    df = df.copy()
    df["date_parsed"] = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce")
    df = df.dropna(subset=["date_parsed"]).sort_values("date_parsed")
    return df.to_dict("records")


def render() -> None:
    st.header("Results")
    st.caption("Quarterly results history + ahead-of-results calendar from NSE events feed.")

    tab_cal, tab_history = st.tabs(["Results Calendar (this week)", "Quarterly History Drill-Down"])

    with tab_cal:
        st.caption("Upcoming corporate events from NSE. Filtered to results-related entries.")
        events = _calendar()
        if not events:
            st.warning("No events from NSE feed.")
        else:
            df = pd.DataFrame(events)
            df["date"] = pd.to_datetime(df["date_parsed"]).dt.date.astype(str)
            # Filter to results-related
            results_kw = df["purpose"].str.contains("Result", case=False, na=False)
            res = df[results_kw].copy()
            # Restrict to next 7 days
            from datetime import date, timedelta
            today = date.today()
            res = res[pd.to_datetime(res["date"]).dt.date.between(today, today + timedelta(days=7))]
            st.write(f"**{len(res)} companies reporting in the next 7 days**")
            st.dataframe(
                res[["date", "symbol", "company", "purpose", "bm_desc"]],
                width="stretch", hide_index=True,
            )

    with tab_history:
        ticker = st.text_input("Ticker (NSE symbol)", value="TCS").strip().upper()
        if not ticker:
            return

        q = _quarterly(ticker)
        if "error" in q:
            st.error(f"Quarterly data unavailable: {q['error']}")
            return

        st.subheader(f"{ticker} — Quarterly snapshot")
        cols = st.columns(5)
        for i, (label, key) in enumerate([
            ("Revenue", "revenue"), ("EBITDA", "ebitda"), ("Net Profit", "net_profit"),
            ("OPM %", "opm_pct"), ("EPS", "eps"),
        ]):
            v = q.get(key)
            if v:
                yoy = v.get("yoy_pct")
                qoq = v.get("qoq_pct")
                cols[i].metric(
                    label, f"{v['latest_value']:,.0f}",
                    delta=(f"YoY {yoy:+.1f}% · QoQ {qoq:+.1f}%"
                           if yoy is not None and qoq is not None else None)
                )

        st.subheader(f"{ticker} — Full quarterly history")
        if "metrics" in q:
            periods = q["periods"]
            metric_keys = ["Sales", "Operating Profit", "OPM %", "Net Profit", "EPS in Rs"]
            rows = []
            for key in metric_keys:
                vals = q["metrics"].get(key, [])
                if not vals: continue
                rows.append({"Metric": key, **{periods[i]: vals[i]
                                                for i in range(min(len(periods), len(vals)))}})
            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(df, width="stretch", hide_index=True)

        st.subheader(f"{ticker} — Shareholding trend (institutional flows)")
        sh = _shareholding(ticker)
        if "error" in sh:
            st.info(f"Shareholding unavailable: {sh['error']}")
        else:
            cols = st.columns(4)
            for i, k in enumerate(["promoters", "fiis", "diis", "public"]):
                latest = sh.get(f"{k}_latest")
                chg = sh.get(f"{k}_qoq_change")
                if latest is not None:
                    cols[i].metric(
                        k.upper(), f"{latest:.2f}%",
                        delta=f"{chg:+.2f}pp QoQ" if chg is not None else None,
                    )
            if "holders" in sh:
                periods = sh["periods"]
                rows = []
                for hkey in ["Promoters", "FIIs", "DIIs", "Government", "Public",
                             "No. of Shareholders"]:
                    vals = sh["holders"].get(hkey, [])
                    if not vals: continue
                    rows.append({"Holder": hkey, **{periods[i]: vals[i]
                                                    for i in range(min(len(periods), len(vals)))}})
                if rows:
                    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
