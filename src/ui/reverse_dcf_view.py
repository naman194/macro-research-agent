"""Reverse-DCF view — implied long-term FCF growth.

Two modes:
  1. Universe scan — every name's market-implied growth, vs historical and
     sector ceiling. Ranks cheap → stretched. Use to spot "what's the market
     telling me?" across a sector or list.
  2. Single-name — full DCF inputs, verdict, scenario table on WACC sensitivity.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import DEFAULT_UNIVERSE
from src.screens.reverse_dcf import (
    ReverseDCFScreener,
    SECTOR_WACC,
    SECTOR_GROWTH_CEILING,
    TERMINAL_GROWTH,
    analyze,
)
from src.ui.components import cross_link_buttons

VERDICT_EMOJI = {"cheap": "🟢", "fair": "⚪", "stretched": "🔴", "na": "—"}


@st.cache_data(ttl=86_400, show_spinner=False)
def _run_universe(universe: tuple) -> dict:
    res = ReverseDCFScreener().run(list(universe))
    return {
        "candidates": res.candidates.to_dict("records"),
        "criteria": res.criteria,
        "rejected_count": res.rejected_count,
        "notes": res.notes,
    }


@st.cache_data(ttl=86_400, show_spinner=False)
def _run_single(ticker: str) -> dict:
    r = analyze(ticker)
    return {
        "ticker": r.ticker,
        "sector_bucket": r.sector_bucket,
        "fcf_base_cr": r.fcf_base_cr,
        "mcap_cr": r.mcap_cr,
        "debt_cr": r.debt_cr,
        "ev_cr": r.ev_cr,
        "wacc": r.wacc,
        "terminal_g": r.terminal_g,
        "implied_growth": r.implied_growth,
        "historical_sales_cagr_5y": r.historical_sales_cagr_5y,
        "historical_profit_cagr_5y": r.historical_profit_cagr_5y,
        "sector_ceiling": r.sector_ceiling,
        "verdict": r.verdict,
        "note": r.note,
        "scenarios": r.scenarios,
        "fetched_ok": r.fetched_ok,
    }


def render() -> None:
    st.header("Reverse-DCF — implied long-term growth")
    st.caption(
        "Instead of asking *is this cheap?*, this view solves for **the FCF "
        "growth rate the market is paying for** and compares it to history "
        "and a sector ceiling. The output is observational — names below "
        "their own track record are *potentially* cheap; names above the "
        "sector ceiling are priced for perfection."
    )

    mode = st.radio(
        "Mode", ["Universe scan", "Single-name deep dive"],
        horizontal=True, label_visibility="collapsed",
    )
    if mode == "Universe scan":
        _render_universe()
    else:
        _render_single()


def _render_universe() -> None:
    universes = {
        "NIFTY 50 core (first 50)":   DEFAULT_UNIVERSE[:50],
        "NIFTY 100 + Next 50 (~100)": DEFAULT_UNIVERSE[:100],
        "Full default universe (~150)": DEFAULT_UNIVERSE,
    }
    choice = st.selectbox("Universe", list(universes.keys()), index=0)
    universe = universes[choice]
    st.caption(
        f"Scanning **{len(universe)} names**. Banks/Finance/Insurance excluded "
        "(FCF-DCF doesn't fit — use embedded value or P-B for those)."
    )

    with st.spinner(f"Scanning {len(universe)} names…"):
        meta = _run_universe(tuple(universe))

    with st.expander("Methodology", expanded=False):
        st.json(meta["criteria"])
        for n in meta["notes"]:
            st.write(f"- {n}")
        st.write(f"**Skipped (financial / missing FCF):** {meta['rejected_count']}")

    cands = pd.DataFrame(meta["candidates"])
    if cands.empty:
        st.warning("No usable output. screener.in may be throttling; retry.")
        return

    # Filters
    col1, col2 = st.columns(2)
    verdict_filter = col1.multiselect(
        "Verdict", ["cheap", "fair", "stretched"], default=["cheap", "stretched"]
    )
    sectors = ["All"] + sorted([s for s in cands["sector"].dropna().unique() if s])
    sector_sel = col2.selectbox("Sector", sectors)

    filtered = cands.copy()
    if verdict_filter:
        filtered = filtered[filtered["verdict"].isin(verdict_filter)]
    if sector_sel != "All":
        filtered = filtered[filtered["sector"] == sector_sel]

    st.write(f"**{len(filtered)} names** match filters")

    display = filtered.copy()
    display["✓"] = display["verdict"].map(VERDICT_EMOJI).fillna("—")
    cols_to_show = ["✓", "ticker", "sector", "verdict",
                    "implied_g_pct", "sales_cagr_5y_pct", "profit_cagr_5y_pct",
                    "ceiling_pct", "wacc_pct", "fcf_cr", "mcap_cr", "note"]
    st.dataframe(
        display[cols_to_show].rename(columns={
            "implied_g_pct": "implied g %",
            "sales_cagr_5y_pct": "5y sales CAGR %",
            "profit_cagr_5y_pct": "5y profit CAGR %",
            "ceiling_pct": "sector ceiling %",
            "wacc_pct": "WACC %",
            "fcf_cr": "FCF (Cr)",
            "mcap_cr": "mcap (Cr)",
        }),
        width="stretch", hide_index=True,
    )


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

    with st.spinner(f"Solving for {ticker}…"):
        r = _run_single(ticker)

    if not r["fetched_ok"]:
        st.error(f"{ticker}: {r['note']}")
        return

    badge = VERDICT_EMOJI.get(r["verdict"], "—")
    ig = r["implied_growth"]
    if ig is None:
        st.markdown(f"### {badge} **{ticker}** — implied growth not solvable")
        st.warning(r["note"])
        return

    st.markdown(
        f"### {badge} **{ticker}** ({r['sector_bucket']}) — "
        f"market-implied growth **{ig*100:.1f}%**"
    )
    st.info(r["note"])

    # Comparison bars
    sales_cagr = r["historical_sales_cagr_5y"]
    profit_cagr = r["historical_profit_cagr_5y"]
    ceiling = r["sector_ceiling"]
    cmp_data = {"market-implied": ig * 100}
    if sales_cagr is not None:  cmp_data["5y sales CAGR"]  = sales_cagr * 100
    if profit_cagr is not None: cmp_data["5y profit CAGR"] = profit_cagr * 100
    cmp_data["sector ceiling"] = ceiling * 100
    cmp_df = pd.DataFrame(cmp_data.items(), columns=["metric", "value (%)"]).set_index("metric")
    st.bar_chart(cmp_df, height=180)

    # Inputs panel
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("FCF base (3y avg)", f"₹{r['fcf_base_cr']:,.0f} Cr")
    c2.metric("Market cap",        f"₹{r['mcap_cr']:,.0f} Cr" if r["mcap_cr"] else "—")
    c3.metric("Borrowings",        f"₹{r['debt_cr']:,.0f} Cr" if r["debt_cr"] else "—")
    c4.metric("WACC / terminal",   f"{r['wacc']*100:.1f}% / {r['terminal_g']*100:.1f}%")

    # Scenario table — WACC sensitivity
    st.markdown("#### Scenario — WACC sensitivity")
    sc_rows = []
    for name, sc in (r.get("scenarios") or {}).items():
        sc_rows.append({
            "scenario": name,
            "WACC %": round(sc["wacc"] * 100, 1),
            "implied growth %": (round(sc["implied_growth"] * 100, 1)
                                  if sc["implied_growth"] is not None else "—"),
        })
    st.dataframe(pd.DataFrame(sc_rows), width="stretch", hide_index=True)

    st.caption(
        "Caveats: cyclicals (metals, autos, capex names) need normalised FCF — "
        "the 3y average partly handles this. Capital-intensive build-out years "
        "depress FCF artificially. Financials are skipped — use embedded value / P-B."
    )

    # Carry as active context + cross-view links
    st.session_state["active_ticker"] = ticker
    st.markdown("---")
    st.caption("Open this ticker in another view:")
    cross_link_buttons(ticker, current_view="🧮 Reverse DCF")
