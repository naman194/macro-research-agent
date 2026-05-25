"""HTML → PDF renderer for the Claude-Design v2 brief.

Wraps WeasyPrint. The input is a complete HTML document produced by
``html_export_v2.render_brief_v2``; the output is a PDF with full CSS fidelity
(Source Serif headlines, mono numbers, sectoral bars, traffic-light regime,
all the editorial styling exactly as the Claude Design specifies).

Why WeasyPrint and not reportlab:
  Reportlab requires us to hand-translate every CSS rule into Python primitives.
  We did that for the legacy PDF and the look diverged from the design. WeasyPrint
  ingests the HTML directly — same source of truth as the HTML download.

System requirements (handled automatically on Streamlit Cloud via ``packages.txt``):
  ``libpango``, ``libcairo``, ``libgdk-pixbuf``. On local macOS without Homebrew,
  WeasyPrint will fail to import; ``available()`` returns False and callers should
  fall back to the legacy reportlab path or instruct the user to use the HTML
  download + browser Cmd+P workflow.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


def available() -> bool:
    """Returns True if WeasyPrint + its system libs are importable + usable."""
    try:
        from weasyprint import HTML  # noqa: F401
        # WeasyPrint imports fine but may fail at render time if cairo/pango
        # libs are missing. Probe with the smallest possible doc.
        HTML(string="<html><body>probe</body></html>").write_pdf()
        return True
    except Exception as exc:
        log.info("WeasyPrint unavailable: %s", str(exc)[:120])
        return False


def html_to_pdf(html_str: str) -> bytes:
    """Render the supplied HTML to PDF bytes using WeasyPrint.

    The HTML should be a complete document — Claude-Design template output.
    External Google Fonts ``<link>`` tags are followed; embedded base64 images
    are honoured; the design's print stylesheet (``@media print``) applies.

    Raises if WeasyPrint isn't installed or can't load system libs.
    """
    from weasyprint import HTML
    return HTML(string=html_str).write_pdf()


def render_brief_pdf_v2(data, kpi_data: Optional[dict] = None,
                        embed_images: Optional[dict] = None) -> bytes:
    """Convenience: build the v2 HTML from DailyNoteData, then render to PDF."""
    from src.agent.html_export_v2 import render_brief_v2
    html_str = render_brief_v2(data, kpi_data=kpi_data, embed_images=embed_images)
    return html_to_pdf(html_str)
