"""Concall AI — upload a transcript PDF, get structured institutional analysis."""
from __future__ import annotations

from datetime import date

import streamlit as st

from src.agent.concall import ConcallAgent, ConcallInput, extract_pdf_text


@st.cache_resource
def _agent() -> ConcallAgent:
    return ConcallAgent()


def render() -> None:
    st.header("Concall AI — Transcript Analyzer")
    st.caption(
        "Upload any concall transcript PDF. Claude extracts management tone, guidance "
        "changes, key concerns, notable Q&A pressure points, and verbatim quotes — "
        "ready to drop into a client note."
    )

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

    uploaded = st.file_uploader("Upload concall transcript PDF",
                                type=["pdf"], accept_multiple_files=False)

    prior_summary = st.text_area(
        "Optional — paste prior-quarter call summary for delta analysis",
        value="", height=120,
        help="If you provide the prior call summary, Claude will highlight what changed."
    )

    text_paste = st.text_area(
        "…or paste transcript text directly (alternative to PDF upload)",
        value="", height=200,
    )

    if st.button("📊 Analyze concall", type="primary"):
        if not ticker or not company:
            st.error("Ticker and company name are required.")
            return

        # Get text either from PDF or paste
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

        with st.spinner("Claude reading the transcript (30-90 seconds for a typical concall)…"):
            note = _agent().analyze(payload)

        st.markdown("---")
        st.markdown(note)

        st.download_button(
            "⬇ Download analysis (Markdown)",
            data=note,
            file_name=f"{ticker}_{quarter.replace(' ','')}_concall_analysis.md",
            mime="text/markdown",
        )
