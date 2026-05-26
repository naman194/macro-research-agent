"""Streamlit entry point — grouped navigation, Home dashboard, consistent chrome."""
from __future__ import annotations

import hashlib
import os

import streamlit as st


# ---------------------------------------------------------------------------
# Access control — only active when SHARED_PASSWORD env var is set.
#
# Auth state lives in TWO places to survive WebSocket reconnects:
#   1. st.session_state["_auth_ok"] — fast in-memory check
#   2. st.query_params["auth"]      — a SHA-256 hash of the password kept in the
#      URL. When Streamlit's WebSocket drops (long-running brief generation,
#      Railway proxy idle timeout, tab refocus on mobile) and session_state
#      resets, the token in the URL still re-authenticates without prompting.
#
# Security model: the URL token IS the access credential — sharing the URL
# (after sign-in) is equivalent to sharing the password. Fine for a small,
# trusted desk; not for retail-public exposure.
# ---------------------------------------------------------------------------
_SHARED_PW = os.getenv("SHARED_PASSWORD", "").strip()


def _expected_token(pw: str) -> str:
    # Salted SHA-256 truncated to 32 hex chars — short enough for a clean URL,
    # long enough that brute force is infeasible.
    return hashlib.sha256(("mra-v1:" + pw).encode("utf-8")).hexdigest()[:32]


if _SHARED_PW:
    expected = _expected_token(_SHARED_PW)
    # If the URL carries the right token, accept it (survives reconnects).
    try:
        url_token = st.query_params.get("auth", "")
    except Exception:
        url_token = ""
    if url_token == expected:
        st.session_state["_auth_ok"] = True

    if not st.session_state.get("_auth_ok"):
        st.set_page_config(
            page_title="Macro Research Agent — Sign in",
            page_icon=":lock:",
            layout="centered",
        )
        st.markdown("### Macro Research Agent")
        st.caption("Institutional research workbench — protected access.")
        with st.form("login"):
            pw = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in")
        if ok:
            if pw == _SHARED_PW:
                st.session_state["_auth_ok"] = True
                # Persist the auth in the URL so WebSocket disconnects don't
                # bounce the user back to the login screen.
                try:
                    st.query_params["auth"] = expected
                except Exception:
                    pass
                st.rerun()
            else:
                st.error("Incorrect password.")
        st.stop()


# Kick off background cache warm-up so the first Daily Morning Brief click
# hits warm SQLite caches across NSE, screener, FRED, GDELT, etc.
# Idempotent + non-blocking — safe even if the first user is signing in.
from src.agent.daily_note import start_warmup as _start_warmup
_start_warmup()

from src.ui import (
    backtest_view,
    calendar_view,
    concall_view,
    daily_note_view,
    earnings_momentum_view,
    fno_view,
    forensics_view,
    garp_view,
    heatmap_view,
    high_conviction_view,
    home_view,
    ideas_view,
    joint_screen_view,
    macro_view,
    note_view,
    performance_view,
    policy_view,
    rebalance_view,
    refresh_view,
    regime_view,
    results_view,
    reverse_dcf_view,
    sector_view,
    smart_money_view,
    special_view,
    technical_view,
)
from src.ui.components import active_ticker_chip, render_nav

st.set_page_config(
    page_title="Macro Research Agent",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)

# Persistent disclaimer banner — institutional context, not retail advice.
st.warning(
    "⚠ **Informational analysis only — NOT investment advice or buy/sell/hold "
    "recommendations.** The author is not a SEBI-registered Research Analyst or "
    "Investment Adviser. Filter outputs, composite scores, scenario ranges, and "
    "structural overlays are model outputs — verify independently before any action. "
    "Past performance is not indicative of future results."
)

# Risk overlay staleness banner (if applicable)
try:
    from src.agent.risk_refresh import staleness_report
    _stale = staleness_report(max_age_days=30)
    if _stale:
        n_never = sum(1 for s in _stale if s.get("last_refreshed") == "never")
        st.warning(
            f"⚠ **Risk overlay refresh needed** — {len(_stale)} sectors "
            f"(of which {n_never} have never been refreshed). Click **Risk Refresh** "
            "in the *Structural* group to run Claude's weekly review."
        )
except Exception:
    pass

# Active-ticker chip — shows the carry-over ticker across views (set by cross-link buttons)
active_ticker_chip()

# Sidebar navigation
view = render_nav(default_view="Home")

# ============================================================
# View dispatch
# ============================================================

if view == "Home":
    home_view.render()
elif view == "Daily Morning Brief":
    daily_note_view.render()
elif view == "🎯 High Conviction":
    high_conviction_view.render()
elif view == "🧩 Joint screen":
    joint_screen_view.render()
elif view == "🔬 Forensics":
    forensics_view.render()
elif view == "🧮 Reverse DCF":
    reverse_dcf_view.render()
elif view == "📈 Earnings momentum":
    earnings_momentum_view.render()
elif view == "Technical / Swing Setups":
    technical_view.render()
elif view == "F&O Analytics":
    fno_view.render()
elif view == "Smart Money":
    smart_money_view.render()
elif view == "Results":
    results_view.render()
elif view == "Concall AI":
    concall_view.render()
elif view == "Structural Heatmap":
    heatmap_view.render()
elif view == "Risk Refresh":
    refresh_view.render()
elif view == "Sector Dashboards":
    sector_view.render()
elif view == "Index Rebalance":
    rebalance_view.render()
elif view == "Econ Calendar":
    calendar_view.render()
elif view == "Performance Tracker":
    performance_view.render()
elif view == "Backtest Engine":
    backtest_view.render()
elif view == "Macro":
    macro_view.render()
elif view == "📊 Regime + RS":
    regime_view.render()
elif view == "Ideas — Quality + Value":
    ideas_view.render()
elif view == "Ideas — GARP":
    garp_view.render()
elif view == "Special Situations":
    special_view.render()
elif view == "Policy & Sentiment":
    policy_view.render()
elif view == "Research note":
    note_view.render()
else:
    # Unknown view (e.g., stale session state) — fall through to Home
    home_view.render()
