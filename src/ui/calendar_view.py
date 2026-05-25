"""Macro economic calendar view."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data.econ_calendar import EconCalendarAdapter


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _upcoming(days: int):
    return EconCalendarAdapter().upcoming(lookahead_days=days)


def render() -> None:
    st.header("Economic Calendar")
    st.caption("India + global macro releases and central-bank meetings. "
               "Hardcoded recurring schedule; refresh annually.")

    days = st.slider("Lookahead window (days)", 7, 90, 30)
    events = _upcoming(days)

    if not events:
        st.warning("No events in window.")
        return

    df = pd.DataFrame(events)
    df["importance_rank"] = df["importance"].map({"high": 0, "medium": 1, "low": 2})

    # Filters
    c1, c2 = st.columns(2)
    imp_filter = c1.selectbox("Min importance", ["all", "medium", "high"], index=0)
    country_filter = c2.multiselect("Country",
                                    sorted(df["country"].unique()),
                                    default=sorted(df["country"].unique()))

    f = df.copy()
    if imp_filter == "high":
        f = f[f["importance"] == "high"]
    elif imp_filter == "medium":
        f = f[f["importance"].isin(["high", "medium"])]
    f = f[f["country"].isin(country_filter)]

    # Display with emoji flags for importance
    f["📊"] = f["importance"].map({"high": "🔴", "medium": "🟡", "low": "⚪"})
    cols = ["📊", "event_date", "country", "indicator", "publisher"]
    f["📥"] = f["url"].apply(lambda u: f"[link]({u})" if u else "")
    cols.append("📥")
    st.write(f"**{len(f)} events**")
    st.dataframe(
        f[cols].sort_values(["event_date", "importance_rank"] if "importance_rank" in f else ["event_date"]),
        width="stretch", hide_index=True,
        column_config={
            "📥": st.column_config.LinkColumn("Source", display_text="open"),
        },
    )

    st.markdown("---")
    st.subheader("Quick read — next high-importance events")
    high_events = [e for e in events if e["importance"] == "high"][:5]
    for e in high_events:
        st.markdown(f"- **{e['event_date']}** · {e['country']} · {e['indicator']} ({e['publisher']})")
