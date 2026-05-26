"""Joint screen — names with multi-signal alignment."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import DEFAULT_UNIVERSE
from src.screens.joint_screen import SIGNAL_LABELS, run_joint_screen
from src.ui.components import cross_link_buttons, page_header


@st.cache_data(ttl=86_400, show_spinner=False)
def _run(universe: tuple, min_alignment: int) -> dict:
    res = run_joint_screen(list(universe), min_alignment=min_alignment)
    return {
        "candidates": res.candidates.to_dict("records"),
        "universe_size": res.universe_size,
        "signals_descriptions": res.signals_descriptions,
        "diagnostics": res.diagnostics,
    }


def render() -> None:
    page_header(
        "Joint screen — multi-signal alignment",
        "A single signal is noise; agreement across independent signals is information. "
        "Names hitting 3+ of the six checks below are where the surface screens, depth "
        "analysis, smart-money flow, and price action all agree.",
    )

    # Signal legend
    with st.expander("What the six signals check"):
        for k, label in SIGNAL_LABELS.items():
            st.write(f"- **{label}** (`{k}`)")
        st.caption(
            "Independence is the point. The signals come from different methodologies "
            "and data sources — fundamentals (Q+V, GARP), cash-flow forensics, "
            "valuation reverse-DCF, smart-money behaviour, and price momentum. "
            "Agreement across multiple is what flags a high-conviction candidate."
        )

    universes = {
        "NIFTY 50 core":              DEFAULT_UNIVERSE[:50],
        "NIFTY 100 + Next 50 (~100)": DEFAULT_UNIVERSE[:100],
        "Full default universe":      DEFAULT_UNIVERSE,
    }
    c1, c2 = st.columns([2, 1])
    choice = c1.selectbox("Universe", list(universes.keys()), index=0)
    min_alignment = c2.slider("Minimum signals firing", 1, 6, 2)

    universe = universes[choice]
    st.caption(
        f"Scanning **{len(universe)} names**. First scan is slow (runs 4 screens "
        "+ smart-money + momentum pull per name); cached 24h afterwards."
    )

    with st.spinner("Running 6-signal joint screen…"):
        out = _run(tuple(universe), min_alignment)

    diag = out["diagnostics"]
    st.caption(
        f"Pass counts in this universe — "
        f"Q+V: **{diag.get('qv_pass', 0)}** · "
        f"GARP: **{diag.get('garp_pass', 0)}** · "
        f"Forensic green: **{diag.get('forensic_green', 0)}** · "
        f"DCF cheap: **{diag.get('dcf_cheap', 0)}** · "
        f"Smart-money buys (uni-wide): **{diag.get('smart_money_universe', 0)}** · "
        f"Momentum positive: **{diag.get('momentum_positive', 0)}**"
    )

    df = pd.DataFrame(out["candidates"])
    if df.empty:
        st.info(
            f"No names in this universe hit ≥ {min_alignment} signals simultaneously. "
            "Lower the threshold or expand the universe."
        )
        return

    st.markdown(f"### {len(df)} candidates")

    # Compact rendering — alignment first, then per-signal check marks
    display = df.copy()
    for sig_key in SIGNAL_LABELS:
        col = f"sig_{sig_key}"
        if col in display.columns:
            display[sig_key] = display[col].map({True: "✓", False: ""}).fillna("")

    show_cols = ["ticker", "alignment_score"] + list(SIGNAL_LABELS.keys()) + \
                ["signals_missing"]
    st.dataframe(
        display[show_cols].rename(columns={
            "alignment_score": "score",
            "signals_missing": "missing",
        }),
        width="stretch", hide_index=True,
    )

    # Quick-jump for the top name
    top_ticker = df.iloc[0]["ticker"]
    st.markdown("---")
    st.caption(
        f"Top alignment: **{top_ticker}** ({df.iloc[0]['alignment_score']}/6 signals). "
        "Open this name in another view:"
    )
    cross_link_buttons(top_ticker, current_view="Joint screen")
