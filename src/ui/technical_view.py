"""Technical / Swing Setups view — full indicator stack + interactive charts per pick."""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from src.agent.swing_charts import build_pick_chart
from src.config import DEFAULT_UNIVERSE
from src.data.prices import PricesAdapter
from src.screens.swing_setups import SwingScanner, _compute_panel, obv_trend_score
from src.ui.components import page_header


@st.cache_data(ttl=1800, show_spinner="Scanning OHLCV + computing 8 indicators per name…")
def _scan(universe: tuple, require_uptrend: bool) -> dict:
    return SwingScanner().scan(list(universe), require_market_uptrend=require_uptrend)


def _render_pick_table(picks: List[Dict[str, Any]], setup_label: str) -> None:
    if not picks:
        st.warning(f"No {setup_label} setups today.")
        return
    df = pd.DataFrame(picks)
    cols = ["ticker", "score", "entry", "stop", "target1", "target2",
            "risk_reward", "risk_pct",
            "rsi", "macd_hist", "adx", "cmf_20", "mfi_14",
            "volume_ratio", "obv_trend",
            "bb_bandwidth_pct", "bb_bandwidth_percentile",
            "rs_60d_pct", "pct_from_52w_high",
            "dma_50", "dma_200"]
    existing = [c for c in cols if c in df.columns]
    st.dataframe(
        df[existing], width="stretch", hide_index=True,
        column_config={
            "score": st.column_config.NumberColumn("Score", format="%.1f"),
            "entry": st.column_config.NumberColumn("Entry", format="%.2f"),
            "stop": st.column_config.NumberColumn("SL", format="%.2f"),
            "target1": st.column_config.NumberColumn("T1", format="%.2f"),
            "target2": st.column_config.NumberColumn("T2", format="%.2f"),
            "risk_reward": st.column_config.NumberColumn("R:R", format="%.2fx"),
            "risk_pct": st.column_config.NumberColumn("Risk %", format="%.1f"),
            "rsi": st.column_config.NumberColumn("RSI", format="%.1f"),
            "macd_hist": st.column_config.NumberColumn("MACD hist", format="%.3f",
                                                       help="MACD histogram. >0 bullish."),
            "adx": st.column_config.NumberColumn("ADX", format="%.0f",
                                                  help="Trend strength. >25 = strong trend."),
            "cmf_20": st.column_config.NumberColumn("CMF(20)", format="%.3f",
                                                     help="Chaikin Money Flow. >0 = accumulation."),
            "mfi_14": st.column_config.NumberColumn("MFI", format="%.0f",
                                                     help="Money Flow Index. <30 oversold, >70 overbought."),
            "volume_ratio": st.column_config.NumberColumn("Vol×", format="%.2f",
                                                          help="Today's volume vs 20d avg."),
            "obv_trend": st.column_config.NumberColumn("OBV trend", format="%.0f",
                                                        help="0-100 rank score. >50 = OBV in upper half of 10d range."),
            "bb_bandwidth_pct": st.column_config.NumberColumn("BB width %", format="%.2f"),
            "bb_bandwidth_percentile": st.column_config.NumberColumn("BB pctile (60d)",
                                                                      format="%.2f",
                                                                      help="Lower = more contracted."),
            "rs_60d_pct": st.column_config.NumberColumn("RS vs Nifty 60d", format="%.1f",
                                                        help="% outperformance vs Nifty."),
            "pct_from_52w_high": st.column_config.NumberColumn("% from 52w H", format="%.1f"),
        },
    )


def _render_chart_panel(picks: List[Dict[str, Any]], setup_label: str,
                        max_charts: int = 5) -> None:
    if not picks:
        return
    st.markdown("**📊 Interactive charts** (top picks)")
    for c in picks[:max_charts]:
        notes_str = " · ".join(c.get("notes", [])) if c.get("notes") else ""
        with st.expander(
            f"📈 **{c['ticker']}** — score {c['score']:.1f} · "
            f"Entry ₹{c['entry']} / SL ₹{c['stop']} / T1 ₹{c['target1']} · R:R {c['risk_reward']:.2f}x"
            + (f"  ·  _{notes_str}_" if notes_str else ""),
            expanded=False,
        ):
            try:
                fig = build_pick_chart(c)
                if fig is None:
                    st.info("Chart unavailable (insufficient history).")
                else:
                    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            except Exception as exc:
                st.warning(f"Chart render failed: {exc}")

            cols = st.columns(4)
            cols[0].metric("RSI", f"{c['rsi']:.1f}")
            cols[1].metric("ADX", f"{c['adx']:.0f}")
            cols[2].metric("CMF(20)", f"{c['cmf_20']:.3f}")
            cols[3].metric("Vol×", f"{c['volume_ratio']:.2f}")


def render() -> None:
    page_header(
        "Technical / Swing Trade Setups",
        "Three strategies stacked: **Trend-Pullback** (high win-rate), **Base-Breakout** "
        "(asymmetric R:R), and **Volume-Breakout** (Wyckoff/Minervini institutional "
        "accumulation prints). Now backed by 8-indicator panel: SMA · RSI · MACD · ADX · "
        "Bollinger · OBV · CMF · MFI · Relative-strength vs Nifty.",
    )

    cols = st.columns([3, 1])
    with cols[1]:
        require_uptrend = st.checkbox(
            "Bear-market guard ON", value=True,
            help="Suppresses long setups when Nifty < 200DMA."
        )

    result = _scan(tuple(DEFAULT_UNIVERSE), require_uptrend)
    st.info(f"**Regime:** {result.get('regime', 'unknown')}")
    st.warning(
        "⚠ **Not investment advice.** Setups shown are output of mechanical filters. "
        "Entry / Stop / Target are model references, not trade recommendations. "
        "Verify independently before any action."
    )

    with st.expander("Strategy methodology — what each filter does", expanded=False):
        for key, desc in (result.get("methodology") or {}).items():
            st.markdown(f"**{key.replace('_', ' ').title()}**")
            st.write(desc)
            st.write("")

    pulls = result.get("trend_pullback", [])
    breaks = result.get("base_breakout", [])
    vols = result.get("volume_breakout", [])

    tab_pull, tab_break, tab_vol = st.tabs([
        f"Trend Pullback ({len(pulls)})",
        f"Base Breakout ({len(breaks)})",
        f"Volume Breakout ({len(vols)})  🆕",
    ])

    with tab_pull:
        st.caption("Historically ~58-65% win rate, 1.8-2.2x R:R. NEW filters: ADX>20, "
                   "MACD>0, OBV slope+, RS vs Nifty 60d+.")
        _render_pick_table(pulls, "trend-pullback")
        st.markdown("---")
        _render_chart_panel(pulls, "trend-pullback")

    with tab_break:
        st.caption("Lower win rate (~45-52%) but bigger winners (3-5x R:R). "
                   "NEW filters: OBV slope+, CMF(20)>0 (institutional accumulation).")
        _render_pick_table(breaks, "base-breakout")
        st.markdown("---")
        _render_chart_panel(breaks, "base-breakout")

    with tab_vol:
        st.caption("Wyckoff/Minervini accumulation play. Long tight base + 2x+ volume spike "
                   "+ price breaks 20d high + CMF>0.1. Lowest frequency, highest conviction "
                   "(~50-55% win rate, 4-6x R:R).")
        _render_pick_table(vols, "volume-breakout")
        st.markdown("---")
        _render_chart_panel(vols, "volume-breakout")

    st.markdown("---")
    # === Preview-any-ticker widget — useful when scanner returns 0 picks ===
    st.subheader("🔎 Preview any ticker (visualise the new indicator stack)")
    st.caption("Type any NSE symbol below to see the full chart + 8-indicator panel — "
               "even if it doesn't pass current setup filters. Useful to spot-check what "
               "the scanner is looking at.")
    preview_ticker = st.text_input("Ticker (NSE symbol)", value="RELIANCE").strip().upper()
    if preview_ticker:
        prices = PricesAdapter()
        nifty = prices.history("^NSEI", period="400d")
        df_t = prices.history(f"{preview_ticker}.NS", period="400d")
        if df_t.empty:
            st.warning(f"No price data for {preview_ticker} — check the ticker.")
        else:
            panel = _compute_panel(df_t, nifty["Close"] if not nifty.empty else None)
            last = panel["last"]
            # Show indicator panel as metrics
            cols = st.columns(8)
            cols[0].metric("Close", f"{float(last['Close']):.1f}")
            cols[1].metric("RSI(14)", f"{float(last['rsi14']):.1f}" if pd.notna(last['rsi14']) else "n/a")
            cols[2].metric("ADX(14)", f"{float(last['adx14']):.0f}" if pd.notna(last['adx14']) else "n/a")
            cols[3].metric("MACD hist", f"{float(last['macd_hist']):+.2f}" if pd.notna(last['macd_hist']) else "n/a")
            cols[4].metric("CMF(20)", f"{float(last['cmf20']):+.3f}" if pd.notna(last['cmf20']) else "n/a")
            cols[5].metric("MFI(14)", f"{float(last['mfi14']):.0f}" if pd.notna(last['mfi14']) else "n/a")
            cols[6].metric("OBV-trend",
                          f"{obv_trend_score(panel['df']['obv'], 10):.0f}")
            cols[7].metric("Vol×",
                          f"{float(last['Volume'])/float(last['vol_avg20']):.2f}x"
                          if last['vol_avg20'] else "n/a")
            # Chart
            try:
                preview_pick = {
                    "ticker": preview_ticker,
                    "entry": float(last["Close"]),
                    "stop": float(last["Close"]) * 0.96,
                    "target1": float(last["Close"]) * 1.06,
                    "target2": float(last["Close"]) * 1.12,
                }
                fig = build_pick_chart(preview_pick)
                if fig:
                    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                    st.caption("_Entry / SL / T1 / T2 lines above are illustrative (±4%/±6%/±12% "
                               "from close) — not a real swing recommendation, just to show "
                               "what the chart looks like with overlays._")
            except Exception as exc:
                st.warning(f"Chart render failed: {exc}")

    st.markdown("---")
    st.caption(
        "**Reference notes only — not recommendations.** Setups described above are output of "
        "mechanical pattern filters. Any decision to size, enter, or exit a position is the "
        "reader's own; the author is not a SEBI-registered Research Analyst or Investment Adviser. "
        "Industry-standard practice for swing setups is to risk 1-2% of capital per trade "
        "(reference, not guidance), use ATR-based or swing-low stops, and trail with the 20DMA "
        "as price moves in the trade's favour."
    )
