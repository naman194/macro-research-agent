"""Concall AI — upload + analyze a transcript, OR view the management track-record.

Two tabs:
  1. Analyze new call — existing flow, now also persists structured extraction
     to concall_history.db so the longitudinal view fills up over time.
  2. Track Record — pulls every stored call for a ticker, surfaces tone drift,
     recurring concerns, guidance churn, and a management credibility score.
"""
from __future__ import annotations

import streamlit as st

from src.agent.bulk_concall_ingest import bulk_ingest, ingest_ticker
from src.agent.concall import ConcallAgent, ConcallInput, extract_pdf_text
from src.agent.concall_history import credibility_report
from src.data.concall_archive import ConcallArchive, list_documents


@st.cache_resource
def _agent() -> ConcallAgent:
    return ConcallAgent()


@st.cache_resource
def _archive() -> ConcallArchive:
    return ConcallArchive()


def render() -> None:
    st.header("Concall AI — Transcript analyzer + management track record")
    st.caption(
        "Upload a concall PDF and Claude produces (1) an institutional analyst note "
        "for the desk and (2) a structured extraction that goes into a longitudinal "
        "store. Over time, the *Track Record* tab builds a quantitative view of "
        "management credibility — tone drift, recurring concerns, guidance churn."
    )

    archive = _archive()
    stats = archive.stats()
    st.caption(f"📚 Archive: **{stats['rows']} calls** stored across "
               f"**{stats['tickers']} tickers**.")

    tab_analyze, tab_history, tab_bulk = st.tabs(
        ["Analyze new call", "Track Record", "Bulk ingest"]
    )

    with tab_analyze:
        _render_analyze_tab()
    with tab_history:
        _render_history_tab()
    with tab_bulk:
        _render_bulk_tab()


# ============================================================
# Analyze tab
# ============================================================

def _render_analyze_tab() -> None:
    with st.expander("Where to download concall transcripts (free sources)"):
        st.markdown("""
- **screener.in** — `https://www.screener.in/company/{TICKER}/consolidated/` → Documents tab
- **AlphaStreet** — https://research.alphastreet.com/
- **Company IR page** — every listed company posts transcripts within 1-2 days of the call
- **BSE corporate filings** — `https://www.bseindia.com/corporates/Comp_Resultsnew.aspx`
- **MoneyControl earnings calls** section
""")

    c1, c2, c3 = st.columns([2, 2, 1])
    ticker = c1.text_input("Ticker", value="").strip().upper()
    company = c2.text_input("Company name", value="").strip()
    quarter = c3.text_input("Quarter", value="Q4 FY26").strip()

    # screener.in Documents discovery — surfaces past transcript URLs for the ticker
    if ticker:
        with st.expander(f"🔗 Documents discovered on screener.in for {ticker}",
                         expanded=False):
            try:
                docs = list_documents(ticker)
                if not docs:
                    st.caption("No transcripts found in the Documents tab — try downloading "
                               "directly from the company IR page or BSE filings.")
                else:
                    st.caption(f"Found {len(docs)} concall-related documents. Click to "
                               "download then upload below for analysis.")
                    for d in docs[:30]:
                        st.markdown(
                            f"- **[{d.inferred_kind or 'doc'}]** {d.inferred_quarter or '?'} "
                            f"— [{d.label}]({d.url})"
                        )
            except Exception as exc:
                st.caption(f"Document discovery failed: {exc}")

    uploaded = st.file_uploader("Upload concall transcript PDF",
                                type=["pdf"], accept_multiple_files=False)

    # Auto-fill prior summary from archive if available
    prior_default = ""
    if ticker:
        latest_prior = _archive().prior(ticker, quarter) if quarter else None
        if latest_prior and latest_prior.markdown_analysis:
            prior_default = latest_prior.markdown_analysis[:2000]

    prior_summary = st.text_area(
        "Prior-quarter call summary for delta analysis",
        value=prior_default, height=120,
        help=("Auto-filled from the archive if a prior quarter has been analyzed for this "
              "ticker. Edit/replace as needed, or leave empty to skip delta analysis."),
    )

    text_paste = st.text_area(
        "…or paste transcript text directly (alternative to PDF upload)",
        value="", height=180,
    )

    persist = st.checkbox(
        "Persist to longitudinal archive (recommended)", value=True,
        help="Saves the structured extraction to concall_history.db. Only structured fields "
             "are kept (tone, guidance items, concerns, positives, pressure points, quotes). "
             "Raw transcript text is NOT stored.",
    )

    if st.button("📊 Analyze concall", type="primary"):
        if not ticker or not company:
            st.error("Ticker and company name are required.")
            return

        transcript_text = ""
        if uploaded is not None:
            pdf_bytes = uploaded.read()
            with st.spinner(f"Extracting text from {uploaded.name}…"):
                transcript_text = extract_pdf_text(pdf_bytes)
            if not transcript_text:
                st.error("Could not extract text from PDF. Try pasting directly.")
                return
            st.success(f"Extracted ~{len(transcript_text.split()):,} words from PDF.")
        elif text_paste.strip():
            transcript_text = text_paste

        if not transcript_text:
            st.error("Please upload a PDF or paste transcript text.")
            return

        payload = ConcallInput(
            ticker=ticker, company_name=company, quarter=quarter,
            transcript_text=transcript_text,
            prior_call_summary=prior_summary or None,
        )

        with st.spinner("Claude reading the transcript (45–120 seconds for a typical concall)…"):
            result = (_agent().analyze_and_persist(payload) if persist
                      else _agent().analyze(payload))

        st.markdown("---")
        if result.parse_ok:
            st.success(
                f"✓ Structured extraction parsed. "
                f"Tone: **{result.tone or '—'}** · "
                f"Net: **{result.net_assessment or '—'}** · "
                f"Guidance items: **{len(result.guidance)}** · "
                f"Concerns: **{len(result.concerns)}**"
                + (" · Saved to archive." if persist else "")
            )
        else:
            st.warning(f"Markdown analysis ready, but structured JSON did not parse "
                       f"({result.parse_error}). The Track Record view will miss this call.")
        st.markdown(result.markdown)

        st.download_button(
            "⬇ Download analysis (Markdown)",
            data=result.markdown,
            file_name=f"{ticker}_{quarter.replace(' ','')}_concall_analysis.md",
            mime="text/markdown",
        )


# ============================================================
# Track Record tab
# ============================================================

def _render_history_tab() -> None:
    archive = _archive()
    tickers = archive.all_tickers()
    if not tickers:
        st.info("No concalls in the archive yet. Analyze a transcript in the **Analyze new call** "
                "tab first — and tick *Persist to longitudinal archive*. Repeat for 4+ quarters "
                "of the same name and this view becomes powerful.")
        return

    col_a, col_b = st.columns([1, 3])
    ticker = col_a.selectbox("Ticker (from archive)", tickers, index=0)
    col_b.caption("Pick a ticker. The view shows tone drift, recurring concerns, "
                  "guidance churn and a credibility score derived from how internally "
                  "consistent management's narrative has been across quarters.")

    if not ticker:
        return

    report = credibility_report(ticker, archive)
    if not report.records:
        st.warning("No records for this ticker in the archive.")
        return

    # Headline
    score = report.credibility_score
    badge = "🟢" if score >= 70 else ("🟠" if score >= 45 else "🔴")
    st.markdown(f"### {badge} **{ticker}** — Management Credibility "
                f"**{score}/100** · {len(report.records)} calls in archive")
    st.info(report.summary)

    # Tone timeline
    st.markdown("#### Tone timeline")
    import pandas as pd
    tone_df = pd.DataFrame([
        {"quarter": r.quarter,
         "call_date": r.call_date or r.fetched_at or "",
         "tone": r.tone or "—",
         "net": r.net_assessment or "—",
         "guidance items": len(r.guidance),
         "concerns": len(r.concerns)}
        for r in report.records
    ])
    st.dataframe(tone_df, width="stretch", hide_index=True)

    # Recurring concerns
    if report.recurring_concerns:
        st.markdown("#### Recurring concerns (appearing in 2+ calls)")
        rc_df = pd.DataFrame([
            {"concern": k, "appeared in": v}
            for k, v in report.recurring_concerns.items()
        ])
        st.dataframe(rc_df, width="stretch", hide_index=True)

    # Guidance churn
    if report.guidance_churn:
        st.markdown("#### Guidance churn — direction distribution")
        gc_df = pd.DataFrame(
            [{"direction": k, "count": v} for k, v in report.guidance_churn.items()]
        )
        st.dataframe(gc_df, width="stretch", hide_index=True)

    # Per-call drilldown
    with st.expander("Per-call detail", expanded=False):
        for r in report.records:
            st.markdown(f"##### {r.quarter} · {r.call_date or 'date unknown'} · tone: {r.tone}")
            if r.guidance:
                gdf = pd.DataFrame(r.guidance)
                st.dataframe(gdf, width="stretch", hide_index=True)
            if r.concerns:
                st.markdown("**Concerns:** " + "; ".join(r.concerns[:6]))
            if r.positives:
                st.markdown("**Positives:** " + "; ".join(r.positives[:6]))
            st.markdown("---")


# ============================================================
# Bulk ingest tab — best-effort auto-fetch + analyze loop
# ============================================================

def _render_bulk_tab() -> None:
    st.markdown("**Auto-ingest transcripts from screener.in's Documents tab.** "
                "For each ticker, the system discovers transcript URLs, attempts to "
                "download the PDF, extracts text, runs the structured Claude analysis, "
                "and saves to the archive.")
    st.caption("Best-effort: PDFs gated behind Cloudflare or auth pages will fail "
               "gracefully. Idempotent — quarters already in the archive are skipped.")

    c1, c2 = st.columns([3, 1])
    tickers_raw = c1.text_input(
        "Tickers (comma-separated NSE symbols)",
        value="", placeholder="e.g. INFY, TCS, RELIANCE",
    )
    max_calls = c2.number_input("Max calls/ticker", min_value=1, max_value=8, value=2)

    if st.button("🚀 Start bulk ingest", type="primary"):
        tickers = [t.strip().upper() for t in tickers_raw.split(",") if t.strip()]
        if not tickers:
            st.error("Provide at least one ticker.")
            return

        progress = st.progress(0.0)
        log_lines: list[str] = []
        results = []
        for i, t in enumerate(tickers):
            with st.spinner(f"Ingesting {t}…"):
                try:
                    s = ingest_ticker(t, max_calls=int(max_calls))
                    results.append(s)
                    log_lines.append(
                        f"**{t}** — attempted {s.attempted} · ingested {s.ingested} · "
                        f"skipped (already) {s.skipped_already} · failed {s.failed}"
                    )
                except Exception as exc:
                    log_lines.append(f"**{t}** — error: {exc}")
            progress.progress((i + 1) / len(tickers))

        st.markdown("---")
        st.markdown("##### Per-ticker summary")
        for line in log_lines:
            st.markdown(f"- {line}")

        # Per-call detail table
        all_rows = []
        for s in results:
            for r in s.results:
                all_rows.append({
                    "ticker": r.ticker, "quarter": r.quarter or "—",
                    "status": r.status, "detail": r.detail[:80],
                    "url": r.url[:60] + "…" if len(r.url) > 60 else r.url,
                })
        if all_rows:
            st.markdown("##### Per-call detail")
            st.dataframe(pd.DataFrame(all_rows), width="stretch", hide_index=True)
