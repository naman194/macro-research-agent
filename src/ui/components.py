"""Shared UI components — keep look-and-feel consistent across views.

Streamlit's default widgets give you a working app, not a polished one. These
helpers wrap the common building blocks (page header, verdict badge, depth-signal
tiles, intent buttons) so adding a new view doesn't reinvent visuals.

Use sparingly. The goal is consistency, not a custom design system.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import streamlit as st


# ============================================================
# Page chrome
# ============================================================

def page_header(title: str, subtitle: Optional[str] = None,
                ticker: Optional[str] = None) -> None:
    """Standard view header. Pass `ticker` to show an active-context chip."""
    chip_html = ""
    if ticker:
        chip_html = (
            f'<span style="background:#e8f1fb;color:#0a3d62;padding:3px 10px;'
            f'border-radius:14px;font-size:0.85em;font-weight:600;'
            f'margin-left:10px;border:1px solid #c8dcf0;">⚓ {ticker}</span>'
        )
    st.markdown(
        f'<h2 style="margin-bottom:4px;">{title}{chip_html}</h2>',
        unsafe_allow_html=True,
    )
    if subtitle:
        st.caption(subtitle)
    st.markdown("<div style='margin-bottom:14px;'></div>", unsafe_allow_html=True)


# ============================================================
# Verdict badges — used everywhere a 🟢/🟠/🔴 verdict needs rendering
# ============================================================

VERDICT_EMOJI: Dict[str, str] = {
    # forensic
    "red": "🔴", "amber": "🟠", "green": "🟢",
    # reverse-DCF
    "cheap": "🟢", "fair": "⚪", "stretched": "🔴",
    # credibility
    "high": "🟢", "medium": "🟠", "low": "🔴",
    # na fallback
    "na": "⚪", None: "⚪",
}


def verdict_badge(verdict: Optional[str], label: Optional[str] = None) -> str:
    """Return a markdown string '🟢 verdict'. Use inline."""
    emoji = VERDICT_EMOJI.get((verdict or "").lower(), "⚪")
    text = label or (verdict or "—")
    return f"{emoji} {text}"


# ============================================================
# Depth tile — the 3-up panel used in research notes / Home
# ============================================================

def depth_signal_tile(
    label: str, value: str, verdict: Optional[str] = None,
    note: Optional[str] = None
) -> None:
    """A metric tile with verdict colour stripe. Use inside st.columns(n)."""
    bg = "#f7f9fc"
    border = {
        "red": "#c53030", "stretched": "#c53030", "low": "#c53030",
        "amber": "#dd8a1a", "medium": "#dd8a1a",
        "green": "#2f855a", "cheap": "#2f855a", "high": "#2f855a",
    }.get((verdict or "").lower(), "#bcbcbc")
    emoji = VERDICT_EMOJI.get((verdict or "").lower(), "⚪")
    note_html = (f'<div style="font-size:0.78em;color:#6b6b6b;margin-top:4px;">'
                 f'{note}</div>' if note else "")
    st.markdown(
        f'<div style="background:{bg};border-left:4px solid {border};'
        f'padding:10px 14px;border-radius:6px;">'
        f'<div style="font-size:0.78em;color:#6b6b6b;text-transform:uppercase;'
        f'letter-spacing:.4px;">{label}</div>'
        f'<div style="font-size:1.35em;font-weight:600;color:#1a1a1a;'
        f'margin-top:2px;">{emoji} {value}</div>'
        f'{note_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# Intent card — "I want to → research a stock" style on Home view
# ============================================================

def intent_card(
    title: str, description: str, *,
    on_click_key: str, target_view: str
) -> bool:
    """Renders an intent card. Click → sets active_view session state and reruns.
    Returns True if clicked this render."""
    clicked = False
    with st.container():
        st.markdown(
            f'<div style="background:#fdfdfd;border:1px solid #e5e8ec;'
            f'border-radius:10px;padding:14px 16px;margin-bottom:8px;">'
            f'<div style="font-weight:600;font-size:1.05em;color:#0a3d62;">{title}</div>'
            f'<div style="color:#444;font-size:0.92em;margin-top:4px;">{description}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if st.button("Open →", key=on_click_key, use_container_width=True):
            st.session_state["active_view"] = target_view
            clicked = True
            st.rerun()
    return clicked


# ============================================================
# Open-in-X cross-links — the buttons that ferry the active ticker across views
# ============================================================

def cross_link_buttons(ticker: str, *, current_view: str) -> None:
    """Renders 'Open in Research Note / Forensics / Reverse DCF / Concall' buttons.
    Skips the current view. Sets st.session_state['active_ticker'] + active_view."""
    targets = [
        ("📝 Research Note", "Research note"),
        ("🔬 Forensics", "🔬 Forensics"),
        ("🧮 Reverse DCF", "🧮 Reverse DCF"),
        ("📞 Concall", "Concall AI"),
    ]
    targets = [(lbl, v) for lbl, v in targets if v != current_view]
    cols = st.columns(len(targets))
    for col, (lbl, v) in zip(cols, targets):
        if col.button(lbl, key=f"xlink_{v}_{ticker}", use_container_width=True):
            st.session_state["active_ticker"] = ticker.upper()
            st.session_state["active_view"] = v
            st.rerun()


def active_ticker_chip() -> Optional[str]:
    """Render the session-wide active-ticker chip if set. Returns the ticker."""
    t = st.session_state.get("active_ticker")
    if not t:
        return None
    st.markdown(
        f'<div style="background:#0a3d62;color:#fff;display:inline-block;'
        f'padding:4px 12px;border-radius:14px;font-size:0.85em;font-weight:600;'
        f'margin-bottom:10px;">⚓ active context: {t}</div>',
        unsafe_allow_html=True,
    )
    return t


# ============================================================
# Sidebar nav — grouped, single-source-of-truth navigation
# ============================================================

# Single source of truth for navigation. (group_emoji, group_label) -> [view names]
NAV_GROUPS = {
    "🏠 Start":        ["Home"],
    "📰 Daily":        ["Daily Morning Brief"],
    "🎯 Stock Ideas":  ["🎯 High Conviction", "🧩 Joint screen",
                        "Ideas — Quality + Value", "Ideas — GARP",
                        "Special Situations"],
    "🔬 Deep Analysis": ["🔬 Forensics", "🧮 Reverse DCF", "📈 Earnings momentum",
                          "Concall AI", "Research note"],
    "📈 Markets & Trend": ["Macro", "📊 Regime + RS", "Technical / Swing Setups",
                            "F&O Analytics", "Smart Money", "Sector Dashboards"],
    "📊 Tools":        ["Backtest Engine", "Performance Tracker", "Index Rebalance",
                        "Econ Calendar", "Results"],
    "🏛 Structural":    ["Structural Heatmap", "Risk Refresh", "Policy & Sentiment"],
}


def render_nav(default_view: str = "Home") -> str:
    """Sidebar navigation with grouped expanders. Returns the active view name."""
    st.sidebar.markdown(
        "<h3 style='margin:0 0 8px 0;color:#0a3d62;'>Macro Research Agent</h3>",
        unsafe_allow_html=True,
    )

    active = st.session_state.get("active_view", default_view)

    # Figure out which group contains the active view so we auto-expand it.
    active_group = None
    for grp, views in NAV_GROUPS.items():
        if active in views:
            active_group = grp
            break
    if active_group is None:
        active_group = list(NAV_GROUPS.keys())[0]
        active = NAV_GROUPS[active_group][0]

    for grp, views in NAV_GROUPS.items():
        with st.sidebar.expander(grp, expanded=(grp == active_group)):
            for v in views:
                is_active = (v == active)
                # Active item gets a different style via markdown; inactive items are buttons.
                if is_active:
                    st.markdown(
                        f'<div style="background:#0a3d62;color:#fff;padding:6px 10px;'
                        f'border-radius:6px;font-weight:600;font-size:0.9em;">'
                        f'▸ {v}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    if st.button(v, key=f"nav_btn_{v}", use_container_width=True):
                        st.session_state["active_view"] = v
                        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.caption(
        "Free data sources: NSE, screener.in, FRED, IMF, World Bank, GDELT, RBI, SEBI. "
        "All output is for research support; **verify before acting**."
    )
    return active
