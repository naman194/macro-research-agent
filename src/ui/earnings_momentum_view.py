"""Earnings momentum — TTM EPS trajectory + acceleration."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import DEFAULT_UNIVERSE
from src.screens.earnings_momentum import EarningsMomentumScreener, analyze
from src.ui.components import page_header, cross_link_buttons


VERDICT_BADGE = {
    "accelerating": "🟢🟢",
    "steady_growth": "🟢",
    "stable": "⚪",
    "decelerating": "🟠",
    "declining": "🔴",
    "na": "—",
}


@st.cache_data(ttl=86_400, show_spinner=False)
def _run(universe: tuple) -> dict:
    res = EarningsMomentumScreener().run(list(universe))
    return {
        "candidates": res.candidates.to_dict("records"),
        "criteria": res.criteria,
        "rejected": res.rejected_count,
        "notes": res.notes,
    }


@st.cache_data(ttl=86_400, show_spinner=False)
def _single(ticker: str) -> dict:
    r = analyze(ticker)
    return {
        "ticker": r.ticker, "fetched_ok": r.fetched_ok, "verdict": r.verdict,
        "ttm_eps_latest": r.ttm_eps_latest, "ttm_eps_prior": r.ttm_eps_prior,
        "ttm_yoy_growth_pct": r.ttm_yoy_growth_pct,
        "early_ttm_yoy_pct": r.early_ttm_yoy_pct,
        "acceleration_pct": r.acceleration_pct,
        "note": r.note,
    }


def render() -> None:
    page_header(
        "Earnings momentum",
        "Trailing-twelve-month EPS trajectory across the universe — the free-data "
        "proxy for sell-side estimate revisions. 'Accelerating' growth is the "
        "strongest single signal.",
    )

    mode = st.radio("Mode", ["Universe scan", "Single name"],
                    horizontal=True, label_visibility="collapsed")
    if mode == "Universe scan":
        _render_universe()
    else:
        _render_single()


def _render_universe() -> None:
    universes = {
        "NIFTY 50 core":              DEFAULT_UNIVERSE[:50],
        "NIFTY 100 + Next 50 (~100)": DEFAULT_UNIVERSE[:100],
        "Full default universe":      DEFAULT_UNIVERSE,
    }
    choice = st.selectbox("Universe", list(universes.keys()), index=0)
    universe = universes[choice]

    st.caption(
        f"Scanning **{len(universe)} names**. Needs 8+ quarters of EPS history per name; "
        "names with fewer are rejected. Cached 24h."
    )

    with st.spinner(f"Computing TTM EPS for {len(universe)} names…"):
        out = _run(tuple(universe))

    cands = pd.DataFrame(out["candidates"])
    if cands.empty:
        st.warning("No data returned. screener.in may be throttling.")
        return

    verdict_filter = st.multiselect(
        "Verdict", ["accelerating", "steady_growth", "stable", "decelerating", "declining"],
        default=["accelerating", "steady_growth", "decelerating", "declining"],
    )
    filtered = cands[cands["verdict"].isin(verdict_filter)] if verdict_filter else cands

    st.write(f"**{len(filtered)} names** · {out['rejected']} rejected for "
             "insufficient EPS history")
    display = filtered.copy()
    display["✓"] = display["verdict"].map(VERDICT_BADGE).fillna("—")

    st.dataframe(
        display[["✓", "ticker", "verdict", "ttm_yoy_pct", "early_ttm_yoy_pct",
                 "acceleration_pp", "ttm_eps_latest", "ttm_eps_prior", "note"]]
        .rename(columns={
            "ttm_yoy_pct": "TTM YoY %", "early_ttm_yoy_pct": "Prior YoY %",
            "acceleration_pp": "Accel (pp)", "ttm_eps_latest": "TTM EPS",
            "ttm_eps_prior": "Prior TTM",
        }),
        width="stretch", hide_index=True,
    )

    with st.expander("Methodology"):
        st.json(out["criteria"])
        for n in out["notes"]:
            st.write(f"- {n}")


def _render_single() -> None:
    col1, col2 = st.columns([1, 3])
    universe_options = sorted(DEFAULT_UNIVERSE)
    carried = st.session_state.get("active_ticker")
    default_idx = universe_options.index(carried) if carried in universe_options \
        else universe_options.index("INFY")
    ticker = col1.selectbox("Ticker", universe_options, index=default_idx)
    custom = col2.text_input(
        "…or any NSE symbol",
        value=(carried if carried and carried not in universe_options else ""),
        placeholder="e.g. POLYCAB",
    ).strip().upper()
    if custom:
        ticker = custom
    if not ticker:
        return

    with st.spinner(f"Computing TTM trajectory for {ticker}…"):
        r = _single(ticker)

    if not r["fetched_ok"]:
        st.error(r.get("note", "fetch failed"))
        return

    badge = VERDICT_BADGE.get(r["verdict"], "—")
    st.markdown(
        f"### {badge} **{ticker}** — verdict **{r['verdict'].replace('_', ' ')}**"
    )
    st.info(r["note"])

    c1, c2, c3 = st.columns(3)
    c1.metric("TTM EPS (latest)", f"₹{r['ttm_eps_latest']}")
    c2.metric("TTM EPS YoY",
              f"{r['ttm_yoy_growth_pct']:+.1f}%" if r['ttm_yoy_growth_pct'] is not None else "—")
    if r["acceleration_pct"] is not None:
        c3.metric("Acceleration", f"{r['acceleration_pct']:+.1f} pp",
                  delta=(f"prior YoY {r['early_ttm_yoy_pct']:+.1f}%"
                         if r['early_ttm_yoy_pct'] is not None else None),
                  delta_color="off")
    else:
        c3.metric("Acceleration", "—", delta="needs 12+ quarters", delta_color="off")

    st.session_state["active_ticker"] = ticker
    st.markdown("---")
    st.caption("Open this ticker in another view:")
    cross_link_buttons(ticker, current_view="Earnings momentum")
