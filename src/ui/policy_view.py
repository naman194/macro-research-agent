"""Policy & Sentiment view — RBI + SEBI feeds + GDELT macro sentiment."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.data.gdelt import GDELTAdapter
from src.data.policy import RBIAdapter, SEBIAdapter


@st.cache_data(ttl=6 * 3600, show_spinner="Pulling RBI press releases…")
def _rbi(limit: int = 30) -> list:
    return RBIAdapter().press_releases(limit)


@st.cache_data(ttl=6 * 3600, show_spinner="Pulling SEBI circulars…")
def _sebi(limit: int = 25) -> list:
    return SEBIAdapter().circulars(limit) + SEBIAdapter().master_circulars(15)


@st.cache_data(ttl=3600, show_spinner=False)
def _gdelt(theme: str, timespan: str = "30d") -> dict:
    return GDELTAdapter().tone(theme, timespan=timespan)


def render() -> None:
    st.header("Policy & Sentiment")
    st.caption("Regulator feeds (RBI, SEBI) + macro news tone (GDELT).")

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("RBI — recent press releases")
        items = _rbi(30)
        if not items:
            st.warning("RBI scraper returned nothing — site may have changed.")
        else:
            for it in items[:20]:
                date = it.get("date") or ""
                st.markdown(f"- {date and f'**{date}** · '}[{it['title']}]({it['url']})")

    with col_b:
        st.subheader("SEBI — recent circulars")
        items = _sebi(25)
        if not items:
            st.warning("SEBI scraper returned nothing — site may have changed.")
        else:
            for it in items[:20]:
                date = it.get("date_hint") or ""
                st.markdown(f"- {date and f'**{date}** · '}[{it['title']}]({it['url']})")

    st.markdown("---")
    st.subheader("Macro news sentiment (GDELT)")
    st.caption(
        "Themes are tracked over the chosen window. Tone is GDELT's average "
        "(-10 negative ↔ +10 positive); volume is article count."
    )

    themes = st.multiselect(
        "Themes",
        ["India economy", "RBI monetary policy", "Indian rupee",
         "Indian banks", "FII outflows", "Indian IT services", "India inflation"],
        default=["India economy", "RBI monetary policy", "Indian rupee"],
    )
    timespan = st.selectbox("Window", ["7d", "14d", "30d", "60d"], index=2)

    if themes:
        rows = []
        for t in themes:
            tone = _gdelt(t, timespan=timespan)
            rows.append({
                "theme": t,
                "articles": tone.get("total_articles", 0),
                "mean_tone": tone.get("mean_tone"),
                "pct_positive": tone.get("pct_positive"),
                "pct_negative": tone.get("pct_negative"),
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch", hide_index=True)

        # Bar chart of mean tone
        if not df.empty and df["mean_tone"].notna().any():
            fig = px.bar(
                df.dropna(subset=["mean_tone"]).sort_values("mean_tone"),
                x="mean_tone", y="theme", orientation="h",
                color="mean_tone", color_continuous_scale="RdYlGn",
                range_color=[-5, 5],
                labels={"mean_tone": "Mean tone (GDELT)", "theme": ""},
            )
            fig.update_layout(height=380, coloraxis_showscale=False)
            st.plotly_chart(fig, width="stretch")
