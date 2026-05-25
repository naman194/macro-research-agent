"""Structural Risk + Catalyst Heatmap — macro disruption landscape at a glance.

Two main visuals:
  1. Sector heatmap — every sector with its risk severity, catalyst strength, and net
     overlay (catalyst - risk). Red = high-risk net negative. Green = high-catalyst net positive.
  2. Drill-down: pick a sector → see all named companies in that sector with their
     individual overlay flags and the net overlay applied to them.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.data.catalysts import (
    COMPANY_CATALYSTS,
    SECTOR_CATALYSTS,
    company_catalysts,
    sector_catalysts,
)
from src.data.structural_risks import (
    COMPANY_STRUCTURAL_RISKS,
    SECTOR_STRUCTURAL_RISKS,
    for_company,
    for_sector,
)


def _sector_rows():
    """Build sector-level rows for the heatmap."""
    all_sectors = sorted(set(list(SECTOR_STRUCTURAL_RISKS.keys()) +
                              list(SECTOR_CATALYSTS.keys())))
    rows = []
    for s in all_sectors:
        r = for_sector(s)
        c = sector_catalysts(s)
        risk_sev = r.get("overall_severity", 0)
        cat_str = c.get("overall_strength", 0)
        risk_pts = round(risk_sev * 30, 1)
        cat_pts = round(cat_str * 15, 1)
        net = round(cat_pts - risk_pts, 1)
        rows.append({
            "sector": s,
            "label": r.get("label") or c.get("label") or s,
            "risk_severity": risk_sev,
            "risk_pts": risk_pts,
            "n_risks": len(r.get("risks", [])),
            "catalyst_strength": cat_str,
            "catalyst_pts": cat_pts,
            "n_catalysts": len(c.get("catalysts", [])),
            "net_overlay_pts": net,
        })
    return pd.DataFrame(rows).sort_values("net_overlay_pts").reset_index(drop=True)


def _company_rows_for_sector(sector: str):
    """All companies in a sector with their overlay metrics."""
    from src.config import TICKER_SECTOR_MAP
    tickers = [t for t, s in TICKER_SECTOR_MAP.items() if s == sector]
    rows = []
    for t in tickers:
        co_risk = for_company(t)
        co_cat = company_catalysts(t)
        sec_risk = for_sector(sector).get("overall_severity", 0)
        sec_cat = sector_catalysts(sector).get("overall_strength", 0)
        sec_pen = sec_risk * 30
        co_pen = co_risk.get("overall_severity", 0) * 15
        sec_bon = sec_cat * 15
        co_bon = co_cat.get("overall_strength", 0) * 10
        net = (sec_bon + co_bon) - (sec_pen + co_pen)
        rows.append({
            "ticker": t,
            "sector_penalty": round(sec_pen, 1),
            "company_penalty": round(co_pen, 1),
            "sector_catalyst": round(sec_bon, 1),
            "company_catalyst": round(co_bon, 1),
            "net_overlay": round(net, 1),
            "company_flags": "; ".join(r["risk"] for r in co_risk.get("risks", [])) or "—",
            "company_catalysts": "; ".join(c["catalyst"] for c in co_cat.get("catalysts", [])) or "—",
        })
    return pd.DataFrame(rows).sort_values("net_overlay", ascending=False).reset_index(drop=True)


def render() -> None:
    st.header("Structural Risk + Catalyst Heatmap")
    st.caption("Macro disruption landscape. **Net overlay** = catalyst bonus − risk penalty. "
               "Red = headwind dominates. Green = tailwind dominates.")

    df = _sector_rows()

    # ---- Top-level sector bar chart ----
    st.subheader("Sectors ranked by net structural overlay")
    fig = px.bar(
        df.sort_values("net_overlay_pts"),
        x="net_overlay_pts", y="sector", orientation="h",
        color="net_overlay_pts",
        color_continuous_scale=[(0, "#b71c1c"), (0.5, "#f5f5f5"), (1, "#0a7e2f")],
        range_color=[df["net_overlay_pts"].min() - 2, df["net_overlay_pts"].max() + 2],
        hover_data={"label": True, "risk_pts": ":.1f", "catalyst_pts": ":.1f",
                    "n_risks": True, "n_catalysts": True},
        labels={"net_overlay_pts": "Net overlay (pts)", "sector": ""},
    )
    fig.update_layout(height=640, coloraxis_showscale=False, margin=dict(l=10, r=10, t=20, b=10))
    fig.add_vline(x=0, line_width=1, line_dash="dash", line_color="grey")
    st.plotly_chart(fig, width="stretch")

    # ---- Sector table view ----
    with st.expander("Sector table (numbers)", expanded=False):
        st.dataframe(
            df[["sector", "label", "risk_pts", "n_risks", "catalyst_pts",
                "n_catalysts", "net_overlay_pts"]],
            width="stretch", hide_index=True,
            column_config={
                "risk_pts": st.column_config.NumberColumn("Risk pts", format="%.1f"),
                "catalyst_pts": st.column_config.NumberColumn("Catalyst pts", format="%.1f"),
                "net_overlay_pts": st.column_config.NumberColumn("Net overlay", format="%.1f"),
            },
        )

    # ---- Drill-down ----
    st.markdown("---")
    st.subheader("Drill-down — pick a sector to see name-level overlays")
    sectors_with_co = sorted(set(s for s in df["sector"]
                                  if any(t in COMPANY_STRUCTURAL_RISKS or t in COMPANY_CATALYSTS
                                         for t in _company_tickers_for_sector(s))))
    if not sectors_with_co:
        st.info("No companies with overlays in any sector yet.")
        return
    selected = st.selectbox("Sector", sectors_with_co, index=0)
    co_df = _company_rows_for_sector(selected)
    if co_df.empty:
        st.info("No companies in this sector universe.")
        return

    st.write(f"**{len(co_df)} companies in {selected}** ranked by net overlay (highest = best risk/reward setup):")
    st.dataframe(
        co_df,
        width="stretch", hide_index=True,
        column_config={
            "sector_penalty": st.column_config.NumberColumn("Sec risk", format="%.1f"),
            "company_penalty": st.column_config.NumberColumn("Co risk", format="%.1f"),
            "sector_catalyst": st.column_config.NumberColumn("Sec cat", format="%.1f"),
            "company_catalyst": st.column_config.NumberColumn("Co cat", format="%.1f"),
            "net_overlay": st.column_config.NumberColumn("Net", format="%.1f"),
        },
    )

    st.markdown("---")
    st.caption("**Refresh cadence:** This data is hand-curated judgment, refreshed quarterly. "
               "Net overlay is a directional signal, not a price target — combine with quant "
               "screens (Q+V / GARP) for entry.")


def _company_tickers_for_sector(sector: str):
    from src.config import TICKER_SECTOR_MAP
    return [t for t, s in TICKER_SECTOR_MAP.items() if s == sector]
