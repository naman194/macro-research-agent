"""Interactive Plotly chart builder for swing-trade picks.

For each candidate, builds a 3-panel chart:
  1. Candlestick + 20/50/200 DMA overlay + Bollinger Bands + entry/SL/T1/T2 lines
  2. Volume with 20d avg line + color-coded bars (green/red by candle direction)
  3. RSI(14) with 30/70 zones

Returns a Plotly Figure that Streamlit renders directly.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.data.prices import PricesAdapter
from src.screens.swing_setups import bollinger_bands, rsi, sma

log = logging.getLogger(__name__)


def build_pick_chart(candidate: Dict[str, Any],
                     prices: Optional[PricesAdapter] = None,
                     lookback_days: int = 220) -> Optional[go.Figure]:
    """Build a 3-panel Plotly chart for a single swing-pick candidate."""
    prices = prices or PricesAdapter()
    ticker = candidate.get("ticker")
    if not ticker:
        return None

    df = prices.history(f"{ticker}.NS", period=f"{lookback_days + 20}d")
    if df.empty or len(df) < 60:
        return None

    df = df.iloc[-lookback_days:].copy()
    df["sma20"] = sma(df["Close"], 20)
    df["sma50"] = sma(df["Close"], 50)
    df["sma200"] = sma(df["Close"], 200)
    df["bb_mid"], df["bb_upper"], df["bb_lower"], _ = bollinger_bands(df["Close"], 20, 2.0)
    df["rsi14"] = rsi(df["Close"], 14)
    df["vol_avg20"] = df["Volume"].rolling(20).mean()

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.62, 0.18, 0.20],
        vertical_spacing=0.03,
        subplot_titles=("Price · DMAs · Bollinger Bands", "Volume", "RSI(14)"),
    )

    # ---------- Panel 1: candlestick + MAs + BB ----------
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="Price",
        increasing_line_color="#0a7e2f", decreasing_line_color="#b71c1c",
        increasing_fillcolor="#0a7e2f", decreasing_fillcolor="#b71c1c",
        showlegend=False,
    ), row=1, col=1)

    # Bollinger Bands shaded area
    fig.add_trace(go.Scatter(
        x=df.index, y=df["bb_upper"], name="BB upper",
        line=dict(color="rgba(120,120,120,0.4)", width=1, dash="dot"),
        showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["bb_lower"], name="BB lower",
        line=dict(color="rgba(120,120,120,0.4)", width=1, dash="dot"),
        fill="tonexty", fillcolor="rgba(120,120,120,0.05)",
        showlegend=False,
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df["sma20"], name="20 DMA",
                             line=dict(color="#0a7e2f", width=1.2, dash="dash")),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["sma50"], name="50 DMA",
                             line=dict(color="#d97706", width=1.2, dash="dash")),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["sma200"], name="200 DMA",
                             line=dict(color="#b71c1c", width=1.4)),
                  row=1, col=1)

    # Entry / SL / T1 / T2 horizontal lines
    entry = candidate.get("entry")
    stop = candidate.get("stop")
    t1 = candidate.get("target1")
    t2 = candidate.get("target2")
    x0, x1 = df.index[0], df.index[-1]
    if entry:
        fig.add_shape(type="line", x0=x0, x1=x1, y0=entry, y1=entry,
                      line=dict(color="#0a3d62", width=1.4, dash="solid"), row=1, col=1)
        fig.add_annotation(x=x1, y=entry, text=f"Entry {entry}", showarrow=False,
                          font=dict(color="#0a3d62", size=10), xanchor="left", row=1, col=1)
    if stop:
        fig.add_shape(type="line", x0=x0, x1=x1, y0=stop, y1=stop,
                      line=dict(color="#b71c1c", width=1.2, dash="dot"), row=1, col=1)
        fig.add_annotation(x=x1, y=stop, text=f"SL {stop}", showarrow=False,
                          font=dict(color="#b71c1c", size=10), xanchor="left", row=1, col=1)
    if t1:
        fig.add_shape(type="line", x0=x0, x1=x1, y0=t1, y1=t1,
                      line=dict(color="#0a7e2f", width=1.2, dash="dot"), row=1, col=1)
        fig.add_annotation(x=x1, y=t1, text=f"T1 {t1}", showarrow=False,
                          font=dict(color="#0a7e2f", size=10), xanchor="left", row=1, col=1)
    if t2:
        fig.add_shape(type="line", x0=x0, x1=x1, y0=t2, y1=t2,
                      line=dict(color="#369c4f", width=1.0, dash="dashdot"), row=1, col=1)
        fig.add_annotation(x=x1, y=t2, text=f"T2 {t2}", showarrow=False,
                          font=dict(color="#369c4f", size=10), xanchor="left", row=1, col=1)

    # ---------- Panel 2: Volume ----------
    vol_colors = [
        "#0a7e2f" if df["Close"].iloc[i] >= df["Open"].iloc[i] else "#b71c1c"
        for i in range(len(df))
    ]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume",
                         marker_color=vol_colors, marker_line_width=0, showlegend=False),
                  row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["vol_avg20"], name="20d avg vol",
                             line=dict(color="#0a3d62", width=1)),
                  row=2, col=1)

    # ---------- Panel 3: RSI ----------
    fig.add_trace(go.Scatter(x=df.index, y=df["rsi14"], name="RSI(14)",
                             line=dict(color="#7c3aed", width=1.4),
                             showlegend=False),
                  row=3, col=1)
    fig.add_hrect(y0=30, y1=70, fillcolor="rgba(150,150,150,0.08)",
                  line_width=0, row=3, col=1)
    fig.add_hline(y=70, line=dict(color="rgba(183,28,28,0.4)", width=1, dash="dot"),
                  row=3, col=1)
    fig.add_hline(y=30, line=dict(color="rgba(10,126,47,0.4)", width=1, dash="dot"),
                  row=3, col=1)

    fig.update_layout(
        height=620,
        margin=dict(l=10, r=10, t=30, b=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                   font=dict(size=9)),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=True,
    )
    fig.update_yaxes(title_text="₹", row=1, col=1, gridcolor="#eee")
    fig.update_yaxes(title_text="", row=2, col=1, gridcolor="#eee", showticklabels=False)
    fig.update_yaxes(title_text="RSI", row=3, col=1, gridcolor="#eee",
                     range=[0, 100], dtick=20)
    fig.update_xaxes(gridcolor="#eee", row=1, col=1, rangebreaks=[dict(bounds=["sat", "mon"])])
    fig.update_xaxes(gridcolor="#eee", row=2, col=1, rangebreaks=[dict(bounds=["sat", "mon"])])
    fig.update_xaxes(gridcolor="#eee", row=3, col=1, rangebreaks=[dict(bounds=["sat", "mon"])])

    return fig
