"""Home dashboard — the landing view.

Three jobs:
  1. Orient new users: what is this thing? show 4 intent cards routing to the
     most-common workflows.
  2. Surface today's signal: top forensic reds, top reverse-DCF cheaps from
     a fast Nifty-50 sweep, archive stats.
  3. Quick-jump: a ticker search box that drops the user into the research
     note for that name with the new depth signals.
"""
from __future__ import annotations

from datetime import date
from typing import List

import streamlit as st

from src.config import DEFAULT_UNIVERSE
from src.data.concall_archive import ConcallArchive
from src.screens.forensics import ForensicsScreener
from src.screens.reverse_dcf import ReverseDCFScreener
from src.ui.components import (
    VERDICT_EMOJI,
    depth_signal_tile,
    intent_card,
    page_header,
)


# Keep the Home-page universe scan small (Nifty-25) so first paint is fast.
HOME_UNIVERSE_SIZE = 25


@st.cache_data(ttl=86_400, show_spinner=False)
def _top_forensic_flags() -> list:
    res = ForensicsScreener().run(list(DEFAULT_UNIVERSE[:HOME_UNIVERSE_SIZE]))
    if res.candidates.empty:
        return []
    df = res.candidates
    df = df[df["verdict"].isin(["red", "amber"])].head(5)
    return df.to_dict("records")


@st.cache_data(ttl=86_400, show_spinner=False)
def _top_cheap_dcf() -> list:
    res = ReverseDCFScreener().run(list(DEFAULT_UNIVERSE[:HOME_UNIVERSE_SIZE]))
    if res.candidates.empty:
        return []
    df = res.candidates
    df = df[df["verdict"] == "cheap"].head(5)
    return df.to_dict("records")


def render() -> None:
    page_header(
        "Macro Research Agent",
        f"Institutional-grade Indian equity research workbench · {date.today():%d %b %Y}",
    )

    # ============================================================
    # Section 1 — Intent cards
    # ============================================================

    st.markdown("##### What do you want to do?")
    c1, c2 = st.columns(2)
    with c1:
        intent_card(
            "📰 Read today's market brief",
            "Pre-market global cues, FII/DII flows, top gainers/losers, screen winners, "
            "F&O read, smart money, catalysts — one institutional-format page.",
            on_click_key="intent_brief", target_view="Daily Morning Brief",
        )
        intent_card(
            "📝 Research a single stock",
            "Full institutional note: fundamentals, valuation picture, bear case, bull "
            "case, with forensic flags + reverse-DCF + concall credibility folded in.",
            on_click_key="intent_research", target_view="Research note",
        )
    with c2:
        intent_card(
            "🎯 Find ideas (multi-signal alignment)",
            "Names where the surface screen agrees with depth: clean earnings quality, "
            "implied growth ≤ track record, technical entry confirmed.",
            on_click_key="intent_ideas", target_view="🎯 High Conviction",
        )
        intent_card(
            "🔬 Run forensic check on a name",
            "9 earnings-quality metrics over 10 years — CFO/PAT, accruals, working-"
            "capital drift, Beneish components, debt-vs-profit divergence.",
            on_click_key="intent_forensic", target_view="🔬 Forensics",
        )

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # ============================================================
    # Section 2 — Today's signals (lightweight Nifty-25 sweep)
    # ============================================================

    st.markdown("##### Today's signal — Nifty 25 sweep")
    st.caption(
        f"Fast scan of {HOME_UNIVERSE_SIZE} large-caps. Full universe in the dedicated "
        "Forensics + Reverse DCF views. Cached 24h."
    )

    tab_flags, tab_cheap, tab_archive = st.tabs(
        ["🚩 Top forensic flags", "💰 Reverse-DCF cheap", "📚 Concall archive"]
    )

    with tab_flags:
        flags = _top_forensic_flags()
        if not flags:
            st.info("No red/amber names in today's sweep.")
        else:
            for r in flags:
                cols = st.columns([1, 1, 3, 3])
                cols[0].markdown(VERDICT_EMOJI.get(r["verdict"], "⚪"))
                cols[1].markdown(f"**{r['ticker']}**")
                cols[2].markdown(f"score **{r['composite_score']}**/100")
                cols[3].caption(r.get("headline_flag", "—"))

    with tab_cheap:
        cheap = _top_cheap_dcf()
        if not cheap:
            st.info("No cheap-DCF names surfaced today (or none with clean FCF).")
        else:
            for r in cheap:
                cols = st.columns([1, 1, 1, 2, 3])
                cols[0].markdown("🟢")
                cols[1].markdown(f"**{r['ticker']}**")
                cols[2].caption(r.get("sector", ""))
                cols[3].markdown(
                    f"implied **{r.get('implied_g_pct','—')}%**"
                    f" vs CAGR {r.get('sales_cagr_5y_pct','—')}%"
                )
                cols[4].caption(r.get("note", "—"))

    with tab_archive:
        arc = ConcallArchive()
        stats = arc.stats()
        tickers = arc.all_tickers()
        st.markdown(
            f"**{stats['rows']} calls** stored across **{stats['tickers']} tickers**."
        )
        if tickers:
            st.caption("Tickers in archive: " + ", ".join(tickers[:30])
                       + (" …" if len(tickers) > 30 else ""))
            st.caption("→ Use the **Concall AI** view's *Track Record* tab to see "
                       "credibility scores.")
        else:
            st.info("No concalls in the archive yet. Analyze a transcript via "
                    "**Concall AI** to start building management track records.")

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # ============================================================
    # Section 3 — Quick-jump ticker
    # ============================================================

    st.markdown("##### Jump to a name")
    col_a, col_b = st.columns([2, 1])
    ticker = col_a.text_input(
        "Ticker (NSE symbol)", value="", placeholder="e.g. INFY, RELIANCE, POLYCAB"
    ).strip().upper()
    target = col_b.selectbox(
        "Open in", ["Research note", "🔬 Forensics", "🧮 Reverse DCF", "Concall AI"],
        index=0,
    )
    if st.button("Go →", disabled=not ticker, use_container_width=False):
        st.session_state["active_ticker"] = ticker
        st.session_state["active_view"] = target
        st.rerun()
