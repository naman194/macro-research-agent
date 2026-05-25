"""High Conviction view — today's picks + watchlist + changes + email-ready brief."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src.agent.hc_publishing import (
    changes_vs_yesterday,
    daily_run,
    generate_hc_email_html,
    history_for_ticker,
    log_qualifications,
    watchlist_add,
    watchlist_all,
    watchlist_remove,
)
from src.config import DEFAULT_UNIVERSE
from src.data.screener_premium import premium_status
from src.screens.high_conviction import evaluate_high_conviction


@st.cache_data(ttl=3600, show_spinner="Running 6-layer composite filter…")
def _run(universe: tuple, require_uptrend: bool):
    picks = evaluate_high_conviction(list(universe),
                                     require_macro_uptrend=require_uptrend)
    return picks


def render() -> None:
    st.header("📊 Composite Screen — Today's Filter Output")
    st.caption(
        "Strictest filter on the platform. A name appears here only if it passes ALL six layers. "
        "Designed around a 6-12 month observation horizon. **This is descriptive filter output, "
        "not a recommendation to buy or hold.**"
    )
    st.warning(
        "⚠ **Not investment advice.** Filter outputs and composite scores are model outputs. "
        "The author is not a SEBI-registered Research Analyst or Investment Adviser. "
        "Verify independently before any action."
    )

    # Premium status indicator
    prem = premium_status()
    if prem["active"]:
        st.success(prem["message"])
    else:
        with st.expander("ℹ Data tier status (click for details)", expanded=False):
            st.info(prem["message"])

    # Run picks
    cols = st.columns([3, 1])
    require_uptrend = cols[1].checkbox(
        "Macro guard ON", value=True,
        help="Suppresses all picks if Nifty below 200DMA."
    )
    picks = _run(tuple(DEFAULT_UNIVERSE), require_uptrend)

    # Log + compute changes
    log_qualifications(picks)
    changes = changes_vs_yesterday([p.ticker for p in picks])

    # Changes panel
    nq = changes.get("newly_qualified") or []
    do = changes.get("dropped_out") or []
    if changes.get("prior_snapshot_date") and (nq or do):
        with st.container():
            st.markdown("---")
            st.subheader(f"📌 Changes since last run ({changes['prior_snapshot_date']})")
            ccols = st.columns(2)
            with ccols[0]:
                if nq:
                    st.success(f"🟢 **Newly qualified ({len(nq)}):** " + ", ".join(nq))
                else:
                    st.info("🟢 No new qualifications today")
            with ccols[1]:
                if do:
                    st.error(f"🔴 **Dropped out ({len(do)}):** " + ", ".join(do))
                else:
                    st.info("🔴 No drop-outs today")

    # Picks display
    st.markdown("---")
    if not picks:
        st.info(
            "🚦 **No names passed today's composite filter.** Macro regime risk-off, "
            "no name passed multi-layer criteria, or technical setups haven't fired."
        )
    else:
        st.success(f"✓ **{len(picks)} name(s) passing all 6 filter layers today.**")
        for p in picks:
            with st.expander(
                f"📊 **{p.ticker}** · {p.name} · "
                f"Composite score **{p.conviction_score:.1f}/100** · "
                f"Sector: {p.sector}",
                expanded=True,
            ):
                st.markdown("**Why the filter highlights this name:**")
                for w in p.why_high_conviction:
                    st.markdown(f"- {w}")
                cols = st.columns(6)
                cols[0].metric("ROCE", f"{p.roce:.1f}%")
                cols[1].metric("ROE", f"{p.roe:.1f}%")
                cols[2].metric("D/E", f"{p.debt_to_equity:.2f}")
                cols[3].metric("Profit CAGR 3y", f"{p.profit_cagr_3y:.0f}%")
                cols[4].metric("P/E", f"{p.pe:.1f}")
                cols[5].metric("Mkt cap (Cr)", f"{p.market_cap_cr:,.0f}")
                scols = st.columns(5)
                scols[0].metric("Net overlay", f"{p.net_overlay:+.1f}")
                scols[1].metric("Last close", f"₹{p.entry:.1f}")
                scols[2].metric("Model stop ref", f"₹{p.stop_loss_suggested:.1f}",
                               f"-{(1 - p.stop_loss_suggested/p.entry)*100:.1f}%")
                scols[3].metric("Setup triggered", p.technical_setup)
                if scols[4].button("➕ Add to watchlist", key=f"wl_{p.ticker}"):
                    if watchlist_add(p.ticker):
                        st.toast(f"Added {p.ticker} to watchlist")

    # ===== Email-ready brief download =====
    st.markdown("---")
    st.subheader("📥 Email-ready brief for client distribution")
    st.caption("Self-contained HTML — paste body into Gmail/Outlook, or send as attachment. "
               "Mobile-friendly + branded.")
    try:
        html = generate_hc_email_html(picks, changes)
        st.download_button(
            "⬇ Download HC Daily Brief (HTML)",
            data=html,
            file_name=f"High_Conviction_Daily_{date.today().isoformat()}.html",
            mime="text/html",
            width="stretch",
            type="primary",
        )
    except Exception as exc:
        st.error(f"Brief generation failed: {exc}")

    # ===== Watchlist =====
    st.markdown("---")
    st.subheader("📋 Watchlist — names you're tracking")
    wl = watchlist_all()
    if not wl:
        st.caption("Empty. Click '➕ Add to watchlist' on any pick above, or add ticker below.")
    else:
        df_wl = pd.DataFrame(wl)
        df_wl["currently_qualified"] = df_wl["ticker"].isin([p.ticker for p in picks])
        # Last qualification date per watchlist name
        df_wl["last_qualified"] = df_wl["ticker"].apply(
            lambda t: (history_for_ticker(t, 1) or [{}])[0].get("snapshot_date", "—")
        )
        st.dataframe(
            df_wl[["ticker", "added_at", "currently_qualified", "last_qualified", "notes"]],
            width="stretch", hide_index=True,
        )

    # Add to watchlist
    add_cols = st.columns([2, 2, 1])
    new_ticker = add_cols[0].text_input("Add ticker to watchlist", placeholder="e.g. RELIANCE")
    new_notes = add_cols[1].text_input("Notes (optional)", placeholder="Why you're tracking")
    if add_cols[2].button("Add", width="stretch"):
        if new_ticker.strip():
            watchlist_add(new_ticker.strip(), new_notes.strip())
            st.toast(f"Added {new_ticker.upper()} to watchlist")
            st.rerun()

    # Remove from watchlist
    if wl:
        rem_cols = st.columns([3, 1])
        to_remove = rem_cols[0].selectbox("Remove from watchlist",
                                          [""] + [w["ticker"] for w in wl])
        if rem_cols[1].button("Remove", width="stretch"):
            if to_remove:
                watchlist_remove(to_remove)
                st.toast(f"Removed {to_remove}")
                st.rerun()

    # ===== Cron instructions =====
    with st.expander("⏰ Automate daily generation (for non-developers)", expanded=False):
        st.markdown("""
**Option A: Open the dashboard each morning** (manual but reliable)
- Bookmark http://localhost:8501
- Click 'High Conviction' → see picks + changes → download HTML → email

**Option B: Schedule daily auto-run on your Mac** (advanced)
Add this to your terminal once:
```
crontab -e
```
Then paste this line (runs 7am IST daily, generates brief, emails it):
```
0 7 * * * cd /Users/naman/macro-research-agent && /Users/naman/macro-research-agent/.venv/bin/python -c "from src.agent.hc_publishing import daily_run; print(daily_run()['picks_count'], 'picks today')"
```
Tell me when you want this set up and I'll walk you through it click by click.
        """)
