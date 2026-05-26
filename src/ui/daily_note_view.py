"""Daily Morning Brief view — polished institutional UI."""
from __future__ import annotations

from datetime import date

import streamlit as st

from src.agent.daily_note import DailyNoteAgent, gather
from src.agent.html_export import markdown_to_html
from src.agent.html_export_v2 import render_brief_v2
from src.agent.pdf_export import markdown_to_pdf
from src.agent.pdf_export_v2 import available as weasyprint_available, html_to_pdf
from src.agent.visuals import (
    global_cues_strip_png,
    kpi_strip_png,
    sectoral_heatmap_png,
)


# Manual cache so we can drive a *stepped* progress UI (st.cache_data only
# supports a single static spinner). 30-minute TTL matches the old behaviour.
_PAYLOAD_CACHE: dict = {"data": None, "ts": 0.0}
_PAYLOAD_TTL_SECONDS = 1800


def _get_or_gather(progress_cb=None) -> dict:
    import time
    from dataclasses import asdict
    now = time.time()
    cached = _PAYLOAD_CACHE.get("data")
    if cached is not None and (now - _PAYLOAD_CACHE["ts"]) < _PAYLOAD_TTL_SECONDS:
        return cached
    d = gather(progress=progress_cb)
    payload = asdict(d)
    _PAYLOAD_CACHE["data"] = payload
    _PAYLOAD_CACHE["ts"] = now
    return payload


def _clear_payload_cache() -> None:
    _PAYLOAD_CACHE["data"] = None
    _PAYLOAD_CACHE["ts"] = 0.0


# Backwards-compatible name for callers that haven't been ported yet.
class _GatherPayloadShim:
    @staticmethod
    def clear():
        _clear_payload_cache()

    def __call__(self):
        return _get_or_gather()


_gather_payload = _GatherPayloadShim()


@st.cache_resource
def _agent() -> DailyNoteAgent:
    return DailyNoteAgent()


def _extract_kpi_data(data) -> dict:
    """Pull the KPI ingredients into a dict that visuals + html can both consume."""
    nifty = next((i for i in (data.indices_snapshot or []) if i.get("index") == "Nifty 50"), None)
    bn = next((i for i in (data.indices_snapshot or []) if i.get("index") == "Bank Nifty"), None)
    sensex = next((i for i in (data.indices_snapshot or []) if i.get("index") == "Sensex"), None)
    fii = next((f for f in (data.fii_dii or []) if f.get("category") in ("FII/FPI", "FII")), None)
    dii = next((f for f in (data.fii_dii or []) if f.get("category") == "DII"), None)
    return {
        "nifty": nifty, "bn": bn, "sensex": sensex,
        "fii_net": fii["net_cr"] if fii else None,
        "dii_net": dii["net_cr"] if dii else None,
        "breadth": data.breadth or {},
    }


def _render_kpi_metrics(kpi_data: dict) -> None:
    """Use Streamlit's native st.metric for in-app KPI cards (looks native)."""
    cols = st.columns(6)
    if kpi_data["nifty"]:
        chg = kpi_data["nifty"].get("change_pct", 0)
        cols[0].metric("Nifty 50", f"{kpi_data['nifty']['close']:,.0f}",
                       f"{chg:+.2f}%")
    if kpi_data["bn"]:
        chg = kpi_data["bn"].get("change_pct", 0)
        cols[1].metric("Bank Nifty", f"{kpi_data['bn']['close']:,.0f}",
                       f"{chg:+.2f}%")
    if kpi_data["sensex"]:
        chg = kpi_data["sensex"].get("change_pct", 0)
        cols[2].metric("Sensex", f"{kpi_data['sensex']['close']:,.0f}",
                       f"{chg:+.2f}%")
    if kpi_data["fii_net"] is not None:
        cols[3].metric("FII Net (₹ Cr)", f"{kpi_data['fii_net']:+,.0f}",
                       "Cash mkt", delta_color="inverse" if kpi_data["fii_net"] < 0 else "normal")
    if kpi_data["dii_net"] is not None:
        cols[4].metric("DII Net (₹ Cr)", f"{kpi_data['dii_net']:+,.0f}", "Cash mkt")
    if kpi_data["breadth"] and kpi_data["breadth"].get("adv_dec_ratio") is not None:
        cols[5].metric("A/D Ratio", f"{kpi_data['breadth']['adv_dec_ratio']:.2f}",
                       f"{kpi_data['breadth'].get('advances',0)}A / {kpi_data['breadth'].get('declines',0)}D")


def render() -> None:
    today_str = date.today().strftime("%d %b %Y")
    st.header(f"📰 Daily Morning Brief — {today_str}")
    st.caption(
        "One-page institutional note synthesizing market action, screen winners, "
        "special-situation catalysts, RBI/SEBI policy, and news sentiment. "
        "Three download formats — PDF for the desk, HTML for email, Markdown for editing."
    )

    cols = st.columns([2, 1])
    with cols[0]:
        generate = st.button("📝 Generate today's morning brief", type="primary",
                             width="stretch")
    with cols[1]:
        refresh = st.button("🔄 Refresh data + regenerate", width="stretch",
                            help="Clears all cached data sources and rebuilds the brief from "
                                 "live NSE / FRED / screener / GDELT / RBI feeds. Takes 60-90s.")
    if refresh:
        _clear_payload_cache()
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.toast("Cache cleared — regenerating now…", icon="🔄")
        # Fall through to generation logic — treat refresh as an explicit Generate.
        generate = True

    if not generate:
        st.info(
            "Click **Generate** to build today's brief. First run ~30-60 seconds "
            "(parallel data pulls). Re-runs instant for 30 minutes. Use **Refresh "
            "data + regenerate** to bypass the cache and pull fresh from every "
            "data source."
        )
        return

    # ---------------- Stepped progress while gather() runs ----------------
    # Cache hit → instant; cache miss → 20-ish parallel pulls showing as ✓ ticks.
    import time
    _t0 = time.time()
    with st.status("Building today's brief…", expanded=True) as status:
        progress_lines = []
        def _cb(label: str) -> None:
            progress_lines.append(label)
            # Keep the last ~10 lines visible so the panel doesn't bloat
            status.update(label=label)
            for line in progress_lines[-10:]:
                pass  # status panel shows the latest label; individual writes below
            st.write(label)
        payload = _get_or_gather(progress_cb=_cb)
        status.update(label=f"✓ Data ready ({time.time()-_t0:.1f}s)", state="complete")

    from src.agent.daily_note import DailyNoteData
    data = DailyNoteData(**payload)

    if data.errors:
        with st.expander(f"⚠ {len(data.errors)} data source(s) had issues — brief still generated"):
            for e in data.errors:
                st.warning(e)

    # ---- KPI strip (Streamlit native metric cards) ----
    kpi_data = _extract_kpi_data(data)
    st.markdown("---")
    st.subheader("Market Snapshot")
    _render_kpi_metrics(kpi_data)

    # ---- Generate the brief ----
    with st.spinner("Claude is writing the brief…"):
        note_md = _agent().generate(data)

    # ---- Log to performance tracker (forward journal + flag snapshots) ----
    try:
        from src.data.performance_tracker import log_flag_snapshot, log_picks
        if data.top_quality_value:
            log_picks("quality_value", data.top_quality_value[:5])
            log_flag_snapshot(data.top_quality_value[:10])
        if data.top_garp:
            log_picks("garp", data.top_garp[:5])
            log_flag_snapshot(data.top_garp[:10])
    except Exception as exc:
        st.info(f"Note: performance journal not updated ({exc})")

    # ---- Build visuals once, reuse for in-app + PDF + HTML ----
    kpi_png = None
    sec_png = None
    cues_png = None
    try:
        kpi_png = kpi_strip_png(
            kpi_data["nifty"], kpi_data["bn"], kpi_data["sensex"],
            kpi_data["fii_net"], kpi_data["dii_net"], kpi_data["breadth"]
        )
    except Exception as exc:
        st.caption(f"_(KPI chart render skipped: {exc})_")
    try:
        sec_png = sectoral_heatmap_png(data.indices_snapshot)
    except Exception as exc:
        st.caption(f"_(Sectoral chart render skipped: {exc})_")
    try:
        cues_png = global_cues_strip_png(data.global_cues)
    except Exception as exc:
        pass

    # ---- Inline visuals (sectoral chart + focus chart) above the note text ----
    if sec_png:
        st.markdown("---")
        st.image(sec_png, width="stretch")

    focus = data.stock_in_focus or {}
    if focus.get("chart_png"):
        st.markdown("---")
        st.subheader(f"🎯 Stock in Focus: {focus.get('ticker','')}")
        st.image(focus["chart_png"], caption=f"{focus.get('ticker','')} — 1Y price action")

    st.markdown("---")
    st.markdown(note_md)

    # ---- Downloads ----
    st.markdown("---")
    st.subheader("📥 Download for distribution")
    embed = {}
    if focus.get("chart_png"):
        embed["focus_chart"] = focus["chart_png"]
    if sec_png:
        embed["sectoral_chart"] = sec_png

    # Add image markers to the note so PDF/HTML pick them up
    note_for_export = note_md
    if sec_png and "{IMG:sectoral_chart}" not in note_for_export:
        # Insert sectoral chart after the Market Action section
        note_for_export = note_for_export.replace(
            "## Market Action — Yesterday",
            "## Market Action — Yesterday\n\n{IMG:sectoral_chart}\n",
            1,
        )

    # HTML — v2 (Claude Design) is the canonical client deliverable; render FIRST so PDF can reuse
    try:
        html_str = render_brief_v2(
            data,
            kpi_data=kpi_data,
            embed_images=embed,
        )
        html_ok = True
    except Exception as exc:
        html_str = ""
        html_ok = False
        st.error(f"HTML (v2) render failed: {exc}")

    # PDF — try WeasyPrint first (renders v2 HTML pixel-faithfully); fall back to
    # legacy reportlab if WeasyPrint or its system libs aren't available locally.
    pdf_bytes = b""
    pdf_ok = False
    pdf_engine = "none"
    if html_ok and weasyprint_available():
        try:
            pdf_bytes = html_to_pdf(html_str)
            pdf_ok = True
            pdf_engine = "weasyprint_v2"
        except Exception as exc:
            st.caption(f"_(WeasyPrint PDF render failed, falling back: {exc})_")
    if not pdf_ok:
        try:
            pdf_bytes = markdown_to_pdf(note_for_export, embed_images=embed)
            pdf_ok = True
            pdf_engine = "reportlab_legacy"
        except Exception as exc:
            st.error(f"PDF render failed (both engines): {exc}")

    # Legacy HTML (markdown-based, kept as fallback)
    try:
        html_legacy = markdown_to_html(
            note_for_export,
            kpi_data=kpi_data,
            embed_images=embed,
        )
        legacy_ok = True
    except Exception as exc:
        html_legacy = ""
        legacy_ok = False

    fname_base = f"India_Morning_Brief_{date.today().isoformat()}"
    c1, c2, c3 = st.columns(3)
    if pdf_ok:
        is_v2 = pdf_engine == "weasyprint_v2"
        c1.download_button(
            ("📄 PDF — Claude Design" if is_v2 else "📄 PDF — basic layout"),
            data=pdf_bytes, file_name=f"{fname_base}.pdf",
            mime="application/pdf", width="stretch",
            help=("Pixel-faithful Claude Design PDF (rendered via WeasyPrint from the same HTML)."
                  if is_v2 else
                  "Fallback PDF using basic reportlab layout. WeasyPrint not available locally "
                  "(no system cairo/pango libs). Use the HTML + browser-print workflow below for "
                  "the Claude Design PDF on this machine. On Streamlit Cloud, the team gets v2 PDF "
                  "automatically."),
        )
    if html_ok:
        c2.download_button(
            "🌐 HTML — for email (Claude Design)",
            data=html_str, file_name=f"{fname_base}.html",
            mime="text/html", width="stretch",
            help="Pixel-faithful Claude Design morning brief — editorial print layout, "
                 "1280px fixed width, self-contained. Opens in any browser; print-friendly.",
        )
    c3.download_button(
        "📝 Markdown — for editing",
        data=note_md, file_name=f"{fname_base}.md",
        mime="text/markdown", width="stretch",
        help="Plain markdown — edit in any text editor before sending.",
    )

    # If we're on legacy PDF (local without WeasyPrint), show the browser-print workflow
    if pdf_ok and pdf_engine != "weasyprint_v2":
        st.info(
            "💡 **For a Claude-Design PDF on this Mac:** download the **HTML** above → open it in "
            "Safari or Chrome → press **`Cmd+P`** → Destination: **Save as PDF** → Paper size: "
            "**Tabloid** (or A3) → **tick 'Background graphics'** → Save. "
            "Gives pixel-perfect editorial PDF identical to the design. "
            "(Your Streamlit Cloud deployment will produce this PDF automatically once it redeploys.)"
        )

    # In-app preview of the v2 HTML
    if html_ok:
        with st.expander("👁 Preview the Claude Design brief in-app"):
            st.components.v1.html(html_str, height=2000, scrolling=True)

    with st.expander("Use legacy design (markdown-based HTML)"):
        st.caption(
            "The legacy HTML uses the older markdown-based template. Kept as a fallback. "
            "The Claude Design (default) is the canonical client deliverable."
        )
        if legacy_ok:
            st.download_button(
                "🌐 HTML — legacy design",
                data=html_legacy, file_name=f"{fname_base}_legacy.html",
                mime="text/html",
                help="Markdown-rendered HTML in the older design system.",
            )
        else:
            st.warning("Legacy HTML render failed.")

    with st.expander("🔍 Raw data the agent used"):
        st.json(payload)
