"""Drill-down — full research note for a single ticker."""
from __future__ import annotations

import streamlit as st

from src.agent.research_note import ResearchAgent, ResearchInput
from src.data.fred import FredAdapter
from src.data.gdelt import GDELTAdapter
from src.data.imf import IMFAdapter
from src.data.nse import NSEAdapter
from src.data.policy import RBIAdapter, SEBIAdapter
from src.data.screener import ScreenerAdapter
from src.screens.special_situations import SpecialSituationsScreener


@st.cache_resource
def _agent() -> ResearchAgent:
    return ResearchAgent()


@st.cache_data(ttl=3600, show_spinner=False)
def _macro_context() -> dict:
    out = {}
    try:
        out["fred"] = FredAdapter().snapshot().to_dict("records")
    except Exception:
        out["fred"] = []
    try:
        out["imf"] = IMFAdapter().latest_table().to_dict("records")
    except Exception:
        out["imf"] = []
    return out


@st.cache_data(ttl=1800, show_spinner="Pulling fundamentals…")
def _fundamentals(ticker: str) -> dict:
    return ScreenerAdapter().fundamentals(ticker)


@st.cache_data(ttl=1800, show_spinner="Pulling NSE filings & quote…")
def _nse_payload(ticker: str) -> dict:
    a = NSEAdapter()
    return {
        "quote": a.quote(ticker),
        "announcements": a.announcements(ticker, lookback_days=90),
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _sentiment(ticker: str, company_name: str) -> dict:
    return GDELTAdapter().sentiment_for_ticker(ticker, company_name=company_name, timespan="14d")


@st.cache_data(ttl=21600, show_spinner=False)
def _policy_items(limit: int = 25) -> list:
    out = []
    for it in RBIAdapter().press_releases(limit):
        it["source"] = "RBI"
        out.append(it)
    for it in SEBIAdapter().circulars(limit):
        it["source"] = "SEBI"
        out.append(it)
    return out


@st.cache_data(ttl=21600, show_spinner=False)
def _special_sits_for(ticker: str) -> list:
    res = SpecialSituationsScreener().run([ticker])
    if res.candidates.empty:
        return []
    return res.candidates.to_dict("records")


def render() -> None:
    st.header("Research Note")
    st.caption("Generate an institutional note for any NSE-listed ticker.")

    seeded = st.session_state.get("last_screen_tickers", []) or []
    default_ticker = seeded[0] if seeded else "RELIANCE"
    ticker = st.text_input(
        "Ticker (NSE symbol, e.g. RELIANCE)", value=default_ticker
    ).strip().upper()

    if not ticker:
        return

    if not st.button("Generate research note", type="primary"):
        st.info("Enter a ticker and click Generate.")
        return

    fundamentals = _fundamentals(ticker)
    nse = _nse_payload(ticker)
    macro = _macro_context()
    company = fundamentals.get("name") or ticker
    with st.spinner("Pulling news sentiment + policy context…"):
        sentiment = _sentiment(ticker, company)
        policy = _policy_items(25)
        special = _special_sits_for(ticker)

    with st.expander("Raw data the agent saw", expanded=False):
        tabs = st.tabs(["Fundamentals", "Quote", "Filings", "Macro", "Sentiment", "Policy", "Special-sit"])
        tabs[0].json(fundamentals)
        tabs[1].json(nse.get("quote", {}))
        tabs[2].json(nse.get("announcements", [])[:10])
        tabs[3].json(macro)
        tabs[4].json(sentiment)
        tabs[5].json(policy[:15])
        tabs[6].json(special)

    payload = ResearchInput(
        ticker=ticker,
        fundamentals=fundamentals,
        filings=nse.get("announcements", []),
        macro_context=macro,
        quote=nse.get("quote"),
        sentiment=sentiment,
        policy_items=policy,
        special_situations=special,
    )

    with st.spinner("Claude is drafting the note…"):
        note = _agent().generate(payload)

    st.markdown("---")
    st.markdown(note)
    st.download_button(
        "Download note (Markdown)",
        data=note,
        file_name=f"{ticker}_research_note.md",
        mime="text/markdown",
    )
