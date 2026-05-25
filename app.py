"""Streamlit entry point — three-tab institutional research dashboard."""
from __future__ import annotations

import streamlit as st

from src.ui import (
    backtest_view,
    calendar_view,
    concall_view,
    daily_note_view,
    fno_view,
    garp_view,
    heatmap_view,
    high_conviction_view,
    ideas_view,
    macro_view,
    note_view,
    performance_view,
    policy_view,
    rebalance_view,
    refresh_view,
    results_view,
    sector_view,
    smart_money_view,
    special_view,
    technical_view,
)

st.set_page_config(
    page_title="Macro Research Agent",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)

st.title("Macro Research Agent")
st.caption(
    "Institutional-grade equity research for Indian markets — macro top-down, "
    "framework-based screening, Claude-generated notes."
)

# Top-of-page staleness banner: warn if any sector's risk overlay is >30 days old.
try:
    from src.agent.risk_refresh import staleness_report
    _stale = staleness_report(max_age_days=30)
    if _stale:
        n_never = sum(1 for s in _stale if s.get("last_refreshed") == "never")
        st.warning(
            f"⚠ **Risk overlay refresh needed** — {len(_stale)} sectors (of which "
            f"{n_never} have never been refreshed). Click **Risk Refresh** in the "
            "sidebar to run Claude's weekly review."
        )
except Exception:
    pass

with st.sidebar:
    st.markdown("### Navigation")
    view = st.radio(
        "View",
        [
            "Daily Morning Brief",
            "🎯 High Conviction",
            "Technical / Swing Setups",
            "F&O Analytics",
            "Smart Money",
            "Results",
            "Concall AI",
            "Structural Heatmap",
            "Risk Refresh",
            "Sector Dashboards",
            "Index Rebalance",
            "Econ Calendar",
            "Performance Tracker",
            "Backtest Engine",
            "Macro",
            "Ideas — Quality + Value",
            "Ideas — GARP",
            "Special Situations",
            "Policy & Sentiment",
            "Research note",
        ],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.markdown(
        "### Notes\n"
        "- Free data sources: NSE, screener.in, FRED, IMF, World Bank, GDELT, RBI, SEBI.\n"
        "- All output is for research support; **verify before acting**."
    )

if view == "Daily Morning Brief":
    daily_note_view.render()
elif view == "🎯 High Conviction":
    high_conviction_view.render()
elif view == "Technical / Swing Setups":
    technical_view.render()
elif view == "F&O Analytics":
    fno_view.render()
elif view == "Smart Money":
    smart_money_view.render()
elif view == "Results":
    results_view.render()
elif view == "Concall AI":
    concall_view.render()
elif view == "Structural Heatmap":
    heatmap_view.render()
elif view == "Risk Refresh":
    refresh_view.render()
elif view == "Sector Dashboards":
    sector_view.render()
elif view == "Index Rebalance":
    rebalance_view.render()
elif view == "Econ Calendar":
    calendar_view.render()
elif view == "Performance Tracker":
    performance_view.render()
elif view == "Backtest Engine":
    backtest_view.render()
elif view == "Macro":
    macro_view.render()
elif view == "Ideas — Quality + Value":
    ideas_view.render()
elif view == "Ideas — GARP":
    garp_view.render()
elif view == "Special Situations":
    special_view.render()
elif view == "Policy & Sentiment":
    policy_view.render()
else:
    note_view.render()
