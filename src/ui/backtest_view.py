"""Backtest view — historical validation of swing + fundamental strategies."""
from __future__ import annotations

import json
from typing import List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.agent.backtest import (
    aggregate_technical_stats,
    backtest_fundamental,
    backtest_high_conviction,
    backtest_technical,
)
from src.config import DEFAULT_UNIVERSE


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _run_technical(tickers: tuple, strategy: str, years: int):
    trades = backtest_technical(list(tickers), strategy=strategy, years=years)
    return [t.__dict__ for t in trades]


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _run_fundamental(tickers: tuple, strategy: str, years: int):
    return backtest_fundamental(list(tickers), strategy=strategy, years=years)


def _equity_curve_chart(equity_curve: List[float], strategy_label: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(equity_curve))), y=equity_curve,
        mode="lines", name=f"{strategy_label} (5% sizing)",
        line=dict(color="#0a3d62", width=2),
    ))
    fig.add_hline(y=1, line=dict(color="grey", width=1, dash="dot"))
    fig.update_layout(
        title="Cumulative equity (each trade sized at 5% of capital)",
        height=320, margin=dict(l=10, r=10, t=40, b=20),
        xaxis_title="Trade #", yaxis_title="Equity (×1.0 start)",
        plot_bgcolor="white", paper_bgcolor="white",
    )
    fig.update_xaxes(gridcolor="#eee")
    fig.update_yaxes(gridcolor="#eee")
    return fig


def _return_dist_chart(returns: List[float]) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=returns, nbinsx=30, marker_color="#0a3d62", opacity=0.85,
    ))
    fig.add_vline(x=0, line=dict(color="red", width=1.5))
    fig.update_layout(
        title="Per-trade return distribution",
        height=300, margin=dict(l=10, r=10, t=40, b=20),
        xaxis_title="Return %", yaxis_title="# trades",
        plot_bgcolor="white", paper_bgcolor="white",
    )
    fig.update_xaxes(gridcolor="#eee")
    fig.update_yaxes(gridcolor="#eee")
    return fig


def render() -> None:
    st.header("📊 Backtest Engine")
    st.caption(
        "Historical validation of our screen + technical strategies. Walks every bar "
        "in the last N years using the same eval code as the live scanner. "
        "Documents honest limitations — survivorship bias, look-ahead on fundamentals, "
        "0.5% slippage applied per trade."
    )

    with st.expander("⚠ Methodology + known biases", expanded=False):
        st.markdown("""
- **Survivorship bias**: universe = current ~50 names. Delisted names absent (overstates returns).
- **Look-ahead on fundamentals**: yfinance gives `as-of` financials, not point-in-time publication. We add a 45-day reporting-lag buffer for entry, but a small leak remains.
- **Slippage**: 0.5% round-trip applied to every trade. Real institutional cost may be lower.
- **No corporate actions** beyond yfinance auto-adjust (splits / bonus handled, dividends in price).
- **Trade sizing in equity curve**: each trade sized at 5% of capital — Kelly-lite, not optimal sizing.
- **Sample size**: 50-name universe + 2-5 years = small sample. Take stats as indicative, not statistically robust.
        """)

    tab_hc, tab_tech, tab_fund = st.tabs([
        "🎯 High Conviction (composite)",
        "Technical strategies",
        "Fundamental (annual rebalance)",
    ])

    # ============================================================
    # High Conviction composite
    # ============================================================
    with tab_hc:
        st.markdown(
            "**The whole-stack strategy.** Names must pass ALL six layers: "
            "(1) fundamental quality — ROCE>=18, ROE>=18, D/E<=0.4, profit CAGR 3y>=15, "
            "mcap>=5,000 Cr; (2) net structural overlay >=0 (catalyst >= risk); "
            "(3) technical setup fires; (4) relative strength vs Nifty >=-5%; "
            "(5) sentiment tone > -3; (6) Nifty above 200DMA. Hold 6m / SL -15%."
        )
        st.info("Target: 60%+ hit rate, positive alpha vs Nifty. "
                "If we hit it on this universe, the strategy is deployable.")

        cols = st.columns([2, 1, 1])
        hc_years = cols[0].slider("Years of history", 2, 5, 4, key="hc_years")
        hc_universe = cols[1].slider("Universe size", 20, 50, 50, key="hc_universe")
        hc_run = cols[2].button("🚀 Run", type="primary", width="stretch", key="hc_run")

        if hc_run:
            tickers = tuple(DEFAULT_UNIVERSE[:hc_universe])
            with st.spinner(f"Backtesting {hc_years}y of High Conviction picks…"):
                res = backtest_high_conviction(list(tickers), years=hc_years)

            if "error" in res:
                st.warning(res["error"])
            else:
                st.markdown("---")
                st.subheader("📊 High Conviction backtest results")
                mcols = st.columns(5)
                mcols[0].metric("Trades", res["n_trades"])
                mcols[1].metric("Hit rate", f"{res['hit_rate_pct']}%",
                               help="% of trades with positive return after slippage")
                mcols[2].metric("Avg return / trade", f"{res['avg_return_pct']:+.2f}%")
                mcols[3].metric("Avg alpha vs Nifty",
                               f"{res['avg_alpha_pct']:+.2f}%" if res['avg_alpha_pct'] is not None else "n/a")
                mcols[4].metric("Avg days held", f"{res['avg_days_held']:.0f}")

                scols = st.columns(4)
                scols[0].metric("Best trade", f"{res['best_return_pct']:+.2f}%")
                scols[1].metric("Worst trade", f"{res['worst_return_pct']:+.2f}%")
                scols[2].metric("Eligible names", res["n_eligible_tickers"])
                scols[3].metric("Alpha hit rate",
                               f"{res['alpha_hit_rate_pct']}%" if res['alpha_hit_rate_pct'] is not None else "n/a",
                               help="% of trades that beat Nifty over same window")

                # Honest verdict
                hr = res["hit_rate_pct"]; ar = res["avg_alpha_pct"] or 0
                if hr >= 60 and ar >= 3:
                    st.success(
                        f"✅ **TARGET MET.** Hit rate {hr}% (target 60%+) and "
                        f"avg alpha {ar:+.2f}% vs Nifty. Strategy validated on this universe. "
                        "Defensible to clients."
                    )
                elif hr >= 60:
                    st.success(
                        f"✅ Hit rate {hr}% achieved. Alpha {ar:+.2f}% is modest — "
                        "strategy beats coin-flip but not crushing Nifty. Still deployable as core."
                    )
                elif hr >= 55:
                    st.info(
                        f"_Hit rate {hr}% — close to target but not crossed._ "
                        "Consider tightening filters or expanding universe."
                    )
                else:
                    st.warning(
                        f"⚠ **Hit rate {hr}% below target.** Current filters insufficient. "
                        "Options: (1) tighten ROCE to 20+, (2) add forward EPS estimates "
                        "(needs paid Refinitiv I/B/E/S), (3) wider universe."
                    )

                st.caption(f"_{res['note']}_")

                with st.expander(f"📋 Full trade log ({len(res['trades'])} trades)",
                                expanded=False):
                    tdf = pd.DataFrame(res["trades"])
                    st.dataframe(
                        tdf[["ticker", "entry_date", "entry_price", "exit_date",
                            "exit_price", "days_held", "return_pct",
                            "nifty_return_pct", "alpha_pct", "exit_reason", "setup", "won"]],
                        width="stretch", hide_index=True,
                    )

                with st.expander("Eligible universe (post all filters)", expanded=False):
                    st.write(", ".join(res["eligible_universe"]))

    # ============================================================
    # Technical
    # ============================================================
    with tab_tech:
        cols = st.columns([2, 2, 1, 1])
        strategy = cols[0].selectbox(
            "Strategy",
            ["trend_pullback", "base_breakout", "volume_breakout"],
            help="Same evaluators the live scanner uses."
        )
        years = cols[1].slider("Years of history", 1, 5, 2)
        universe_size = cols[2].slider("Universe size", 5, 50, 15,
                                       help="More names = more trades but slower (10-30s per 5 names).")
        run = cols[3].button("🚀 Run", type="primary", width="stretch")

        if run:
            tickers = tuple(DEFAULT_UNIVERSE[:universe_size])
            with st.spinner(f"Walking {years}y × {len(tickers)} names through {strategy}…"):
                trades = _run_technical(tickers, strategy, years)

            if not trades:
                st.warning("No trades fired in the backtest period. Try a longer window "
                           "or a larger universe.")
                return

            stats = aggregate_technical_stats(
                [type("T", (), t)() for t in trades]
                if isinstance(trades[0], dict) else trades
            ) if False else aggregate_technical_stats(
                [_to_obj(t) for t in trades]
            )

            # Headline metrics
            st.markdown("---")
            st.subheader(f"Results: {strategy} — {years}y, {len(tickers)} names")
            mcols = st.columns(5)
            mcols[0].metric("Trades", stats["n_trades"])
            mcols[1].metric("Win rate", f"{stats['win_rate_pct']}%")
            mcols[2].metric("Avg return / trade",
                            f"{stats['avg_return_pct']:+.2f}%")
            mcols[3].metric("Expectancy", f"{stats['expectancy_r']:.2f} R")
            mcols[4].metric("Avg days held", f"{stats['avg_days_held']:.0f}")

            scols = st.columns(4)
            scols[0].metric("Best trade", f"{stats['best_trade_pct']:+.2f}%")
            scols[1].metric("Worst trade", f"{stats['worst_trade_pct']:+.2f}%")
            scols[2].metric("Median", f"{stats['median_return_pct']:+.2f}%")
            scols[3].metric("Final equity", f"{stats['cumulative_equity_5pct_sized']:.3f}×")

            st.markdown("**Exit reasons**")
            st.write(", ".join(f"**{k}**: {v}" for k, v in
                              stats["exit_reason_counts"].items()))

            # Charts
            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(_equity_curve_chart(stats["equity_curve"], strategy),
                               width="stretch", config={"displayModeBar": False})
            with c2:
                returns = [t["return_pct"] for t in trades]
                st.plotly_chart(_return_dist_chart(returns),
                               width="stretch", config={"displayModeBar": False})

            # Trade log
            with st.expander(f"📋 Full trade log ({len(trades)} trades)", expanded=False):
                df = pd.DataFrame(trades)
                show_cols = ["ticker", "entry_date", "entry_price", "stop",
                            "exit_date", "exit_price", "exit_reason",
                            "days_held", "return_pct", "r_multiple", "won"]
                st.dataframe(
                    df[show_cols].sort_values("entry_date", ascending=False),
                    width="stretch", hide_index=True,
                    column_config={
                        "return_pct": st.column_config.NumberColumn("Return %", format="%.2f"),
                        "r_multiple": st.column_config.NumberColumn("R", format="%.2f"),
                    },
                )

            # Honest assessment
            if stats["expectancy_r"] > 0.3 and stats["win_rate_pct"] > 50:
                st.success(
                    f"✓ **Positive expectancy ({stats['expectancy_r']:.2f}R) with "
                    f"{stats['win_rate_pct']}% win rate.** Strategy validated on this universe "
                    "over this period — but verify on more years / larger universe before claiming."
                )
            elif stats["expectancy_r"] > 0:
                st.info(
                    f"_Marginal positive expectancy ({stats['expectancy_r']:.2f}R)._ "
                    "Either filters are over-restrictive or the period was unfavorable. "
                    "Try a longer lookback or wider universe."
                )
            else:
                st.warning(
                    f"⚠ **Negative expectancy ({stats['expectancy_r']:.2f}R) over this window.** "
                    "Strategy unprofitable here — could be regime-specific (sideways tape) "
                    "or the filters need recalibration. Don't deploy capital based on these specific filters yet."
                )

    # ============================================================
    # Fundamental
    # ============================================================
    with tab_fund:
        cols = st.columns([2, 1, 1])
        f_strategy = cols[0].selectbox(
            "Fundamental strategy",
            ["quality_value", "garp"],
            help="Q+V: ROE>=15, D/E<=0.5, growth>0. GARP: ROE>=12, profit growth>=12."
        )
        f_years = cols[1].slider("Years tested", 2, 4, 3,
                                 help="Annual rebalance. Limited by yfinance 5y annual data.")
        f_universe = cols[2].slider("Universe", 10, 50, 25)
        f_run = cols[2].button("🚀 Run", type="primary", width="stretch",
                              key="fund_run")

        if f_run:
            tickers = tuple(DEFAULT_UNIVERSE[:f_universe])
            with st.spinner(f"Running {f_years}y annual-rebalance backtest…"):
                res = _run_fundamental(tickers, f_strategy, f_years)

            if "error" in res:
                st.warning(res["error"])
                return

            st.markdown("---")
            st.subheader(f"Results: {f_strategy} — {res['years_tested']} annual rebalances")
            mcols = st.columns(5)
            mcols[0].metric("Total picks", res["total_picks"])
            mcols[1].metric("Win rate", f"{res['overall_win_rate_pct']}%")
            mcols[2].metric("Avg return / pick", f"{res['overall_avg_return_pct']:+.2f}%")
            mcols[3].metric("Avg alpha vs Nifty",
                           f"{res['avg_yearly_alpha_pct']:+.2f}%" if res['avg_yearly_alpha_pct'] is not None else "n/a")
            mcols[4].metric("Best pick", f"{res['best_pick_return_pct']:+.2f}%")

            # Yearly breakdown
            st.markdown("**Year-by-year:**")
            yb = pd.DataFrame(res["yearly_breakdown"])
            cols_show = ["entry_date", "exit_date", "n_picks", "avg_return_pct",
                        "win_rate_pct", "nifty_return_pct", "alpha_pct"]
            st.dataframe(
                yb[cols_show], width="stretch", hide_index=True,
                column_config={
                    "avg_return_pct": st.column_config.NumberColumn("Avg return %", format="%+.2f"),
                    "win_rate_pct": st.column_config.NumberColumn("Win %", format="%.1f"),
                    "nifty_return_pct": st.column_config.NumberColumn("Nifty %", format="%+.2f"),
                    "alpha_pct": st.column_config.NumberColumn("Alpha %", format="%+.2f"),
                },
            )

            # Honest interpretation
            if res["avg_yearly_alpha_pct"] and res["avg_yearly_alpha_pct"] > 5:
                st.success(f"✓ **Strategy generated {res['avg_yearly_alpha_pct']:+.2f}% avg "
                          "alpha** over Nifty across the tested years. Defensible.")
            elif res["avg_yearly_alpha_pct"] and res["avg_yearly_alpha_pct"] > 0:
                st.info(f"_Marginal positive alpha ({res['avg_yearly_alpha_pct']:+.2f}%)._ "
                       "Within noise range — needs more years to be conclusive.")
            elif res["avg_yearly_alpha_pct"] is not None:
                st.warning(f"⚠ **Strategy underperformed Nifty by "
                          f"{abs(res['avg_yearly_alpha_pct']):.2f}%** on average. "
                          "Could be regime-specific (Q+V underperforms in speculative bulls) "
                          "or filter recalibration needed.")

            # Pick-level detail
            with st.expander("🔍 All picks (year-by-year)", expanded=False):
                for yr in res["yearly_breakdown"]:
                    st.markdown(f"**{yr['entry_date']} → {yr['exit_date']}** "
                               f"(Nifty: {yr['nifty_return_pct']:+.2f}%)")
                    pdf = pd.DataFrame(yr["picks"])
                    if not pdf.empty:
                        st.dataframe(
                            pdf[["ticker", "entry_price", "exit_price", "return_pct",
                                "roe", "pg", "sg", "de"]],
                            width="stretch", hide_index=True,
                        )


# Helper to convert dict back to obj-like for aggregate_technical_stats
def _to_obj(d):
    o = type("T", (), {})()
    for k, v in d.items():
        setattr(o, k, v)
    return o
