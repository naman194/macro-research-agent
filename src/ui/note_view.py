"""Drill-down — full research note for a single ticker.

Pulls every depth-signal we have on a name (fundamentals + filings + macro +
sentiment + policy + special-situations + forensic earnings-quality +
reverse-DCF implied growth + concall management credibility) and hands it
to Claude as one structured prompt."""
from __future__ import annotations

import streamlit as st

from src.agent.concall_history import credibility_report as _credibility_report
from src.agent.research_note import ResearchAgent, ResearchInput
from src.data.fred import FredAdapter
from src.data.gdelt import GDELTAdapter
from src.data.imf import IMFAdapter
from src.data.nse import NSEAdapter
from src.data.policy import RBIAdapter, SEBIAdapter
from src.data.screener import ScreenerAdapter
from src.screens.forensics import analyze as forensic_analyze
from src.screens.reverse_dcf import analyze as reverse_dcf_analyze
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


@st.cache_data(ttl=86_400, show_spinner=False)
def _forensic_payload(ticker: str) -> dict:
    """Slim forensic report — composite + verdict + top red/amber notes.
    Full time-series stays in the Forensics view; the agent only needs the verdict."""
    r = forensic_analyze(ticker)
    if not r.fetched_ok:
        return {}
    top = [
        {"metric": name, "verdict": m.verdict, "note": m.note}
        for name, m in r.metrics.items()
        if m.verdict in ("red", "amber")
    ]
    return {
        "composite_score": r.composite_score,
        "verdict": r.verdict,
        "headline_flag": r.headline_flag,
        "flags": top[:6],
    }


@st.cache_data(ttl=86_400, show_spinner=False)
def _reverse_dcf_payload(ticker: str) -> dict:
    r = reverse_dcf_analyze(ticker)
    if not r.fetched_ok or r.implied_growth is None:
        # Return the note so Claude knows why it's missing (e.g. skipped: financial)
        return {"verdict": r.verdict, "note": r.note} if r.note else {}
    pct = lambda x: round(x * 100, 1) if x is not None else None
    return {
        "sector_bucket": r.sector_bucket,
        "verdict": r.verdict,
        "implied_growth_pct": pct(r.implied_growth),
        "sales_cagr_5y_pct": pct(r.historical_sales_cagr_5y),
        "profit_cagr_5y_pct": pct(r.historical_profit_cagr_5y),
        "sector_ceiling_pct": pct(r.sector_ceiling),
        "wacc_pct": pct(r.wacc),
        "fcf_base_cr": r.fcf_base_cr,
        "note": r.note,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _concall_credibility_payload(ticker: str) -> dict:
    r = _credibility_report(ticker)
    if not r.records:
        return {}
    return {
        "credibility_score": r.credibility_score,
        "tone_stability": r.tone_stability,
        "concern_resolution": r.concern_resolution,
        "guidance_discipline": r.guidance_discipline,
        "pressure_recurrence": r.pressure_recurrence,
        "summary": r.summary,
        "n_calls_in_archive": len(r.records),
        "top_recurring_concerns": list(r.recurring_concerns.keys())[:5],
        "guidance_churn": r.guidance_churn,
    }


def render() -> None:
    st.header("Research Note")
    st.caption("Generate an institutional note for any NSE-listed ticker.")

    # Priority: active_ticker (cross-view link) > last_screen_tickers > default
    carried = st.session_state.get("active_ticker")
    seeded = st.session_state.get("last_screen_tickers", []) or []
    default_ticker = carried or (seeded[0] if seeded else "RELIANCE")
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
    with st.spinner("Pulling news sentiment + policy context + depth signals…"):
        sentiment = _sentiment(ticker, company)
        policy = _policy_items(25)
        special = _special_sits_for(ticker)
        forensic = _forensic_payload(ticker)
        rdcf = _reverse_dcf_payload(ticker)
        credibility = _concall_credibility_payload(ticker)

    # Inline preview tiles for the three new depth signals
    c1, c2, c3 = st.columns(3)
    badge = {"red":"🔴","amber":"🟠","green":"🟢","cheap":"🟢","fair":"⚪","stretched":"🔴"}
    if forensic.get("verdict"):
        c1.metric("Forensic risk", f"{forensic.get('composite_score','—')}/100",
                  delta=f"{badge.get(forensic['verdict'],'')} {forensic['verdict']}",
                  delta_color="off")
    else:
        c1.metric("Forensic risk", "—")
    if rdcf.get("verdict") and rdcf.get("implied_growth_pct") is not None:
        c2.metric("Reverse-DCF implied g",
                  f"{rdcf['implied_growth_pct']}%",
                  delta=f"{badge.get(rdcf['verdict'],'')} {rdcf['verdict']}",
                  delta_color="off")
    else:
        c2.metric("Reverse-DCF implied g", "—",
                  delta=(rdcf.get('note') or 'no FCF data')[:40], delta_color="off")
    if credibility.get("credibility_score") is not None:
        score = credibility["credibility_score"]
        ic = "🟢" if score >= 70 else ("🟠" if score >= 45 else "🔴")
        c3.metric("Mgmt credibility",
                  f"{score}/100",
                  delta=f"{ic} {credibility['n_calls_in_archive']} calls",
                  delta_color="off")
    else:
        c3.metric("Mgmt credibility", "—", delta="no concalls archived", delta_color="off")

    with st.expander("Raw data the agent saw", expanded=False):
        tabs = st.tabs(["Fundamentals", "Quote", "Filings", "Macro", "Sentiment",
                        "Policy", "Special-sit", "Forensic", "Reverse-DCF", "Credibility"])
        tabs[0].json(fundamentals)
        tabs[1].json(nse.get("quote", {}))
        tabs[2].json(nse.get("announcements", [])[:10])
        tabs[3].json(macro)
        tabs[4].json(sentiment)
        tabs[5].json(policy[:15])
        tabs[6].json(special)
        tabs[7].json(forensic)
        tabs[8].json(rdcf)
        tabs[9].json(credibility)

    payload = ResearchInput(
        ticker=ticker,
        fundamentals=fundamentals,
        filings=nse.get("announcements", []),
        macro_context=macro,
        quote=nse.get("quote"),
        sentiment=sentiment,
        policy_items=policy,
        special_situations=special,
        forensic_report=forensic or None,
        reverse_dcf_report=rdcf or None,
        concall_credibility=credibility or None,
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

    # Carry this ticker as the active context + cross-view links
    st.session_state["active_ticker"] = ticker
    st.markdown("---")
    st.caption("Open this ticker in another view:")
    from src.ui.components import cross_link_buttons
    cross_link_buttons(ticker, current_view="Research note")
