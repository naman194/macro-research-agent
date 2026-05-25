"""Performance tracker view — forward journal + lookback proxy."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import DEFAULT_UNIVERSE
from src.data.performance_tracker import (
    flag_retrospective,
    journal_hit_rate,
    journal_summary,
    lookback_aggregate,
    lookback_returns,
)


@st.cache_data(ttl=1800, show_spinner=False)
def _journal(framework: str = None):
    df = journal_summary(framework)
    return df.to_dict("records") if not df.empty else []


@st.cache_data(ttl=1800, show_spinner=False)
def _journal_stats(framework: str = None, min_days: int = 30):
    return journal_hit_rate(framework, min_days_held=min_days)


@st.cache_data(ttl=1800, show_spinner="Computing historical lookback returns…")
def _lookback(tickers: tuple, horizons: tuple):
    df = lookback_returns(list(tickers), list(horizons))
    return df.to_dict("records") if not df.empty else []


@st.cache_data(ttl=1800, show_spinner=False)
def _lookback_agg(tickers: tuple, horizons: tuple):
    return lookback_aggregate(list(tickers), list(horizons))


def render() -> None:
    st.header("Performance Tracker")
    st.caption("Two views: forward journal (logs every daily-brief pick → realized return) "
               "and historical lookback (what current screen candidates would have returned).")

    tab_journal, tab_lookback, tab_flags = st.tabs(
        ["Forward Journal", "Historical Lookback", "Flag Retrospective"]
    )

    with tab_journal:
        st.subheader("Logged picks (auto-populated each time the Daily Brief is generated)")
        framework = st.selectbox(
            "Framework", ["All", "quality_value", "garp"], index=0
        )
        fw = None if framework == "All" else framework

        journal = _journal(fw)
        if not journal:
            st.info("No picks logged yet. Generate the Daily Morning Brief — it will start "
                    "logging top Q+V and GARP picks each time. After ~30 days, you'll have "
                    "enough data to see realized win rate.")
        else:
            df = pd.DataFrame(journal)
            min_days = st.slider("Evaluate picks held at least N days", 0, 90, 7)
            stats = _journal_stats(fw, min_days)
            cols = st.columns(4)
            cols[0].metric("Total picks logged", stats.get("total_picks", 0))
            cols[1].metric("Evaluable", stats.get("evaluable_picks", 0))
            cols[2].metric("Win rate",
                          f"{stats['win_rate_pct']}%" if stats.get('win_rate_pct') is not None else "n/a")
            cols[3].metric("Avg return",
                          f"{stats['avg_return_pct']:.2f}%" if stats.get('avg_return_pct') is not None else "n/a")
            if "note" in stats:
                st.info(stats["note"])

            display = df[["pick_date", "framework", "ticker", "rank",
                         "entry_price", "current_price", "return_pct", "days_held"]]
            st.dataframe(display.sort_values("pick_date", ascending=False),
                         width="stretch", hide_index=True)

    with tab_lookback:
        st.subheader("If you'd bought these tickers N days ago…")
        st.caption("Uses current universe's prices to show realized returns at different "
                   "holding periods. Quick sanity check on screen quality.")
        tickers_default = ", ".join(DEFAULT_UNIVERSE[:20])
        tickers_input = st.text_area("Tickers (comma-separated)",
                                     value=tickers_default, height=80)
        tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
        horizons = [30, 90, 180, 365]

        if tickers:
            agg = _lookback_agg(tuple(tickers), tuple(horizons))
            if agg.get("n_tickers"):
                st.write(f"**Sample size: {agg['n_tickers']} tickers**")
                rows = []
                for hkey, st_v in agg["by_horizon"].items():
                    rows.append({"Horizon": hkey, **st_v})
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            df = pd.DataFrame(_lookback(tuple(tickers), tuple(horizons)))
            if not df.empty:
                st.dataframe(df, width="stretch", hide_index=True)

    with tab_flags:
        st.subheader("Flag Retrospective — is our structural judgment validated by the tape?")
        st.caption("Every time the Daily Brief runs, we log the structural penalty + "
                   "catalyst bonus for each screened name. After 30+ days, we can check: "
                   "did high-penalty names actually underperform low-penalty ones?")
        min_days = st.slider("Min days held to evaluate", 7, 180, 30)
        retro = flag_retrospective(min_days_held=min_days)
        st.write(f"**Snapshots logged:** {retro.get('snapshots', 0)}  ·  "
                 f"**Evaluable (≥{min_days}d):** {retro.get('evaluable', 0)}")
        if retro.get("note"):
            st.info(retro["note"])
        if retro.get("penalty_bucket_stats"):
            st.markdown("**Returns by risk-penalty bucket** "
                        "(should be: high penalty → low return if judgment is correct)")
            st.dataframe(pd.DataFrame(retro["penalty_bucket_stats"]),
                         width="stretch", hide_index=True)
        if retro.get("catalyst_bucket_stats"):
            st.markdown("**Returns by catalyst-bonus bucket** "
                        "(should be: high catalyst → high return)")
            st.dataframe(pd.DataFrame(retro["catalyst_bucket_stats"]),
                         width="stretch", hide_index=True)
        if retro.get("interpretation"):
            st.caption(retro["interpretation"])
