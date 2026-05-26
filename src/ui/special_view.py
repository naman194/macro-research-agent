"""Special Situations view — catalyst-driven events with proximity-weighted scoring."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.screens.special_situations import SpecialSituationsScreener
from src.ui.components import page_header


@st.cache_data(ttl=21600, show_spinner="Scanning NSE events feed…")  # 6h
def _run(universe: tuple) -> dict:
    # Empty universe = scan all events, not just the default universe
    res = SpecialSituationsScreener().run(list(universe) if universe else [])
    return {
        "candidates": res.candidates.to_dict("records"),
        "criteria": res.criteria,
        "notes": res.notes,
    }


def render() -> None:
    page_header(
        "Special Situations — Event-driven Catalysts",
        "Buybacks, bonus, splits, fund-raising from the live NSE board-meeting feed. "
        "Scored by event weight × proximity-to-date.",
    )

    restrict = st.checkbox("Restrict to my curated universe (NIFTY-50ish)", value=False)
    if restrict:
        from src.config import DEFAULT_UNIVERSE
        meta = _run(tuple(DEFAULT_UNIVERSE))
    else:
        meta = _run(tuple())

    with st.expander("Scoring methodology", expanded=False):
        st.json(meta["criteria"])
        for n in meta["notes"]:
            st.write(f"- {n}")

    cands = pd.DataFrame(meta["candidates"])
    if cands.empty:
        st.warning("No special-situation events in current NSE feed.")
        return

    c1, c2 = st.columns(2)
    event_types = sorted(cands["event_type"].dropna().unique())
    sel_types = c1.multiselect("Event type", event_types, default=event_types)
    max_days = c2.slider("Max days to event", 0, 90, 30)

    f = cands[cands["event_type"].isin(sel_types) & (cands["days_out"].fillna(99) <= max_days)]

    st.write(f"**{len(f)} events** match filters")
    st.dataframe(
        f[["ticker", "name", "event_type", "event_date", "days_out", "score",
           "purpose", "description"]],
        width="stretch", hide_index=True,
    )

    st.session_state["last_screen_tickers"] = f["ticker"].tolist()
