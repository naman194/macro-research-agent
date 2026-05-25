"""Markdown → PDF renderer (pure Python via reportlab).

Handles the subset of markdown the daily note actually uses:
  - H1 / H2 / H3 headings
  - Paragraphs
  - Bullet lists
  - Inline **bold**, *italic*, [text](url), inline `code`
  - Horizontal rules

Output is institutional-style: serif body, sans headings, clean margins.
"""
from __future__ import annotations

import io
import re
from typing import List, Optional, Tuple

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


_BRAND = HexColor("#0a3d62")    # institutional navy
_BRAND_LIGHT = HexColor("#1d5b8a")
_ACCENT = HexColor("#d97706")    # warm amber accent
_INK = HexColor("#1a1a1a")
_MUTED = HexColor("#555")
_RULE = HexColor("#d0d0d0")
_GREEN = HexColor("#0a7e2f")
_RED = HexColor("#b71c1c")
_AMBER = HexColor("#d97706")
_TABLE_HEAD = HexColor("#e8eef5")
_CARD_BG = HexColor("#f7f9fc")

# Filter-status → badge color mapping (neutral observational language)
# Replaces the old BUY/HOLD/AVOID recommendation badges.
_STATUS_COLORS = {
    "PASSES": _GREEN,
    "BORDERLINE": HexColor("#6b7280"),
    "FAILS": _RED,
}


def _styles():
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "brand", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=12, leading=14, textColor=white, alignment=TA_LEFT,
        ),
        "brand_right": ParagraphStyle(
            "brand_right", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9, leading=12, textColor=white, alignment=TA_RIGHT,
        ),
        "brand_tag": ParagraphStyle(
            "brand_tag", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8, leading=10, textColor=HexColor("#cbd5e1"), alignment=TA_LEFT,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=20, leading=24, textColor=_BRAND, spaceAfter=4, spaceBefore=0,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, leading=16, textColor=_BRAND, spaceAfter=4, spaceBefore=14,
        ),
        "h3": ParagraphStyle(
            "h3", parent=base["Heading3"], fontName="Helvetica-Bold",
            fontSize=11, leading=14, textColor=_INK, spaceAfter=4, spaceBefore=8,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10, leading=14, textColor=_INK, alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10, leading=13.5, textColor=_INK, alignment=TA_LEFT,
            leftIndent=10,
        ),
        "muted": ParagraphStyle(
            "muted", parent=base["BodyText"], fontName="Helvetica-Oblique",
            fontSize=8.5, leading=11, textColor=_MUTED, spaceBefore=8,
        ),
        "section_intro": ParagraphStyle(
            "section_intro", parent=base["BodyText"], fontName="Helvetica-Oblique",
            fontSize=9, leading=12, textColor=_MUTED, spaceAfter=8, spaceBefore=2,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.5, leading=9, textColor=_MUTED, alignment=TA_CENTER,
        ),
    }


def _inline(md: str) -> str:
    """Convert markdown inline syntax to reportlab paragraph mini-language."""
    s = md
    # Links: [text](url)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
               lambda m: f'<link href="{m.group(2)}" color="#0a58ca"><u>{m.group(1)}</u></link>',
               s)
    # Bold then italic
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", s)
    # Inline code
    s = re.sub(r"`([^`]+)`", r'<font face="Courier" size="9">\1</font>', s)

    # Filter-status labels → colored observation badges (neutral language)
    def _status_repl(m):
        status = m.group(1).upper()
        color = _STATUS_COLORS.get(status, _MUTED)
        return (f'<font color="{color.hexval()}" face="Helvetica-Bold">'
                f'&nbsp;■&nbsp;{status}&nbsp;</font>')
    s = re.sub(r"\b(PASSES|BORDERLINE|FAILS)\b", _status_repl, s)

    return s


def _header_band(title: str, subtitle: str) -> Table:
    """Brand band at top of first page — title left, tagline below, subtitle right."""
    styles = _styles()
    left_cell = [
        Paragraph(title, styles["brand"]),
        Paragraph("INSTITUTIONAL EQUITY RESEARCH · INDIA", styles["brand_tag"]),
    ]
    band = Table(
        [[left_cell, Paragraph(subtitle, styles["brand_right"])]],
        colWidths=["70%", "30%"],
    )
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BRAND),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    return band


def _section_header(text: str) -> Table:
    """H2-style section header with left accent bar."""
    styles = _styles()
    title_style = ParagraphStyle(
        "sec_h", parent=styles["h2"], spaceBefore=0, spaceAfter=0,
        leftIndent=10,
    )
    tbl = Table([[Paragraph(text, title_style)]], colWidths=["100%"])
    tbl.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, -1), 4, _BRAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#fafbfd")),
    ]))
    return tbl


def _status_badge_inline(status: str) -> str:
    """Returns reportlab inline markup for a colored observation badge.
    Status one of: PASSES / BORDERLINE / FAILS (neutral filter outcomes, not recommendations)."""
    color = _STATUS_COLORS.get(status.upper(), _MUTED)
    return (f'<font color="{color.hexval()}" face="Helvetica-Bold" size="11">'
            f'■ {status}</font>')


def _on_page(canvas, doc):
    """Called on every page — draws footer with page number + disclaimer."""
    canvas.saveState()
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 7.5)
    page_w = A4[0]
    foot_y = 0.7 * cm
    canvas.line(1.8 * cm, foot_y + 0.6 * cm, page_w - 1.8 * cm, foot_y + 0.6 * cm)
    canvas.setStrokeColor(_RULE)
    canvas.drawString(
        1.8 * cm, foot_y,
        "For institutional use only · Not investment advice · Verify all figures before action",
    )
    canvas.drawRightString(page_w - 1.8 * cm, foot_y, f"Page {doc.page}")
    canvas.restoreState()


def _parse_md_table(lines: List[str], start: int):
    """Parse a contiguous markdown table starting at `lines[start]`.

    Returns (rows: list[list[str]], next_index)."""
    rows = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        row_txt = lines[i].strip().strip("|")
        cells = [c.strip() for c in row_txt.split("|")]
        # Skip the separator line (---|---|---)
        if all(re.match(r"^:?-+:?$", c) for c in cells):
            i += 1
            continue
        rows.append(cells)
        i += 1
    return rows, i


def _make_table(rows: List[List[str]]) -> Table:
    """Style a markdown table as a reportlab Table with green/red for % columns."""
    styles = _styles()
    cell_para = ParagraphStyle("cell", parent=styles["body"], fontSize=9.5,
                               leading=12, alignment=TA_LEFT, spaceAfter=0)
    data = []
    for r_idx, row in enumerate(rows):
        new_row = []
        for cell in row:
            new_row.append(Paragraph(_inline(cell), cell_para))
        data.append(new_row)

    tbl = Table(data, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _TABLE_HEAD),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#fafafa")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, _RULE),
        ("BOX", (0, 0), (-1, -1), 0.4, _RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    # Color % columns based on sign
    if rows:
        for c_idx, header in enumerate(rows[0]):
            if "%" in header:
                for r_idx in range(1, len(rows)):
                    val = rows[r_idx][c_idx] if c_idx < len(rows[r_idx]) else ""
                    if val.startswith("-"):
                        style.append(("TEXTCOLOR", (c_idx, r_idx), (c_idx, r_idx), _RED))
                    elif val and val[0].isdigit():
                        style.append(("TEXTCOLOR", (c_idx, r_idx), (c_idx, r_idx), _GREEN))
    tbl.setStyle(TableStyle(style))
    return tbl


def markdown_to_pdf(md: str, brand_title: str = "India Morning Brief",
                    brand_subtitle: str = "Institutional Research · Confidential",
                    embed_images: Optional[dict] = None) -> bytes:
    """Render a markdown string to a PDF; return PDF bytes.

    `embed_images`: optional dict mapping `{IMG:key}` placeholders in the markdown
    to PNG bytes. Anywhere the marker appears on its own line, the image is embedded.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.4 * cm, bottomMargin=1.6 * cm,
        title=brand_title,
    )
    styles = _styles()
    flow: List = [_header_band(brand_title, brand_subtitle), Spacer(1, 12)]

    embed_images = embed_images or {}

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if not line.strip():
            i += 1
            continue

        # Image embed marker: {IMG:key}
        img_match = re.match(r"\{IMG:([^}]+)\}", line.strip())
        if img_match:
            key = img_match.group(1)
            img_bytes = embed_images.get(key)
            if img_bytes:
                img = Image(io.BytesIO(img_bytes), width=17 * cm, height=8 * cm,
                            kind="proportional")
                flow.append(img)
                flow.append(Spacer(1, 6))
            i += 1
            continue

        # Markdown table?
        if line.strip().startswith("|"):
            rows, next_i = _parse_md_table(lines, i)
            if rows:
                flow.append(_make_table(rows))
                flow.append(Spacer(1, 6))
            i = next_i
            continue

        if line.startswith("# "):
            flow.append(Paragraph(_inline(line[2:].strip()), styles["h1"]))
            flow.append(HRFlowable(width="100%", thickness=0.6, color=_RULE,
                                   spaceBefore=2, spaceAfter=8))
            i += 1
            continue

        if line.startswith("## "):
            flow.append(_section_header(_inline(line[3:].strip())))
            flow.append(Spacer(1, 4))
            i += 1
            continue

        if line.startswith("### "):
            flow.append(Paragraph(_inline(line[4:].strip()), styles["h3"]))
            i += 1
            continue

        if line.startswith("---"):
            flow.append(HRFlowable(width="100%", thickness=0.4, color=_RULE,
                                   spaceBefore=4, spaceAfter=4))
            i += 1
            continue

        if line.startswith("- "):
            # Collect a contiguous bullet block
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(ListItem(Paragraph(_inline(lines[i][2:].strip()),
                                                styles["bullet"]),
                                      leftIndent=8))
                i += 1
            flow.append(ListFlowable(items, bulletType="bullet", start="•",
                                     leftIndent=14, bulletFontSize=9))
            flow.append(Spacer(1, 3))
            continue

        # Italics-only stub message
        if line.startswith("_") and line.endswith("_"):
            flow.append(Paragraph(_inline(line), styles["muted"]))
            i += 1
            continue

        # Default: paragraph
        # Group consecutive non-empty, non-special lines into one paragraph
        para = [line]
        i += 1
        while (i < len(lines) and lines[i].strip()
               and not lines[i].startswith(("#", "-", "---", "_"))):
            para.append(lines[i].rstrip())
            i += 1
        flow.append(Paragraph(_inline(" ".join(para)), styles["body"]))

    doc.build(flow, onFirstPage=_on_page, onLaterPages=_on_page)
    buf.seek(0)
    return buf.read()
