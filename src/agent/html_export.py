"""HTML brief exporter — interactive, mobile-friendly, email-safe.

Renders the morning brief as a standalone .html file. Designed to:
  - Look polished in a browser (Chrome / Safari / mobile)
  - Render reasonably in email clients (Gmail / Outlook / Apple Mail)
  - Be self-contained — all CSS inline, all images base64 embedded — so a single
    file can be downloaded and forwarded

Components:
  - Branded header band (navy)
  - KPI strip at top: Nifty, Bank Nifty, Sensex, FII net, DII net, A/D ratio
  - Section nav (sticky-ish on long pages)
  - Markdown body rendered with the `markdown` library
  - Recommendation badges (BUY / HOLD / AVOID coloured)
  - Footer with disclaimer + generation timestamp
"""
from __future__ import annotations

import base64
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import markdown as md_lib


# Brand palette — same as PDF
_BRAND = "#0a3d62"
_BRAND_LIGHT = "#1d5b8a"
_ACCENT = "#d97706"
_INK = "#1a1a1a"
_MUTED = "#6b7280"
_GREEN = "#0a7e2f"
_RED = "#b71c1c"
_LIGHT = "#f5f7fa"
_CARD = "#ffffff"
_BORDER = "#e2e8f0"

# Filter-status colors (neutral observational language — not recommendations)
_STATUS_COLORS = {
    "PASSES": _GREEN,
    "BORDERLINE": _MUTED,
    "FAILS": _RED,
}


def _b64_img(png_bytes: bytes, mime: str = "image/png") -> str:
    if not png_bytes:
        return ""
    return f"data:{mime};base64,{base64.b64encode(png_bytes).decode()}"


def _badge_html(status: str) -> str:
    color = _STATUS_COLORS.get(status.upper(), _MUTED)
    return (f'<span style="display:inline-block;padding:3px 10px;'
            f'background:{color};color:white;border-radius:4px;'
            f'font-weight:700;font-size:12px;letter-spacing:0.5px;'
            f'vertical-align:middle;">{status.upper()}</span>')


def _replace_rec_badges(html: str) -> str:
    """Replace observational filter-status words with colored chips. Neutral, not recommendations."""
    pattern = r"\b(PASSES|BORDERLINE|FAILS)\b"
    return re.sub(pattern, lambda m: _badge_html(m.group(1)), html)


def _kpi_cards_html(nifty, bn, sensex, fii_net, dii_net, breadth) -> str:
    cards = []

    def card(label, value, sub, sub_color, accent):
        return f"""
        <div style="flex:1;min-width:120px;background:{_CARD};border:1px solid {_BORDER};
                    border-radius:8px;padding:12px 16px;display:flex;flex-direction:column;
                    border-left:4px solid {accent};">
            <div style="font-size:10px;font-weight:700;color:{_MUTED};letter-spacing:0.5px;
                        text-transform:uppercase;">{label}</div>
            <div style="font-size:18px;font-weight:700;color:{_INK};margin-top:6px;">{value}</div>
            <div style="font-size:11px;font-weight:600;color:{sub_color};margin-top:4px;">{sub}</div>
        </div>
        """

    if nifty:
        chg = nifty.get("change_pct", 0)
        cards.append(card("NIFTY 50", f"{nifty['close']:,.0f}",
                          f"{chg:+.2f}%", _GREEN if chg >= 0 else _RED,
                          _GREEN if chg >= 0 else _RED))
    if bn:
        chg = bn.get("change_pct", 0)
        cards.append(card("BANK NIFTY", f"{bn['close']:,.0f}",
                          f"{chg:+.2f}%", _GREEN if chg >= 0 else _RED,
                          _GREEN if chg >= 0 else _RED))
    if sensex:
        chg = sensex.get("change_pct", 0)
        cards.append(card("SENSEX", f"{sensex['close']:,.0f}",
                          f"{chg:+.2f}%", _GREEN if chg >= 0 else _RED,
                          _GREEN if chg >= 0 else _RED))
    if fii_net is not None:
        cards.append(card("FII NET (₹ Cr)", f"{fii_net:+,.0f}",
                          "Cash mkt", _GREEN if fii_net >= 0 else _RED,
                          _GREEN if fii_net >= 0 else _RED))
    if dii_net is not None:
        cards.append(card("DII NET (₹ Cr)", f"{dii_net:+,.0f}",
                          "Cash mkt", _GREEN if dii_net >= 0 else _RED,
                          _GREEN if dii_net >= 0 else _RED))
    if breadth and breadth.get("adv_dec_ratio") is not None:
        adr = breadth["adv_dec_ratio"]
        cards.append(card("A/D RATIO", f"{adr:.2f}",
                          f"{breadth.get('advances',0)}A / {breadth.get('declines',0)}D",
                          _GREEN if adr >= 1 else _RED,
                          _GREEN if adr >= 1 else _RED))

    if not cards:
        return ""
    return (f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin:20px 0;">'
            f'{"".join(cards)}</div>')


def _section_nav_html(md_text: str) -> str:
    """Extract H2 sections from markdown and build a sticky-ish nav row."""
    sections = re.findall(r"^##\s+(.+)$", md_text, flags=re.M)
    if len(sections) < 3:
        return ""
    links = []
    for s in sections[:12]:
        s_clean = s.strip()
        anchor = re.sub(r"[^a-z0-9]+", "-", s_clean.lower()).strip("-")
        links.append(
            f'<a href="#{anchor}" style="color:{_BRAND};text-decoration:none;'
            f'padding:4px 10px;border-radius:4px;background:{_LIGHT};'
            f'font-size:11px;font-weight:600;white-space:nowrap;">{s_clean}</a>'
        )
    return (f'<div style="display:flex;gap:6px;flex-wrap:wrap;padding:12px;'
            f'background:{_CARD};border:1px solid {_BORDER};border-radius:8px;'
            f'margin:12px 0;">{"".join(links)}</div>')


def _add_section_anchors(html: str) -> str:
    """Add id="..." anchors to <h2> tags so the nav can scroll-link to them."""
    def repl(m):
        text = m.group(1)
        anchor = re.sub(r"[^a-z0-9]+", "-",
                        re.sub(r"<[^>]+>", "", text).lower()).strip("-")
        return f'<h2 id="{anchor}">{text}</h2>'
    return re.sub(r"<h2>(.+?)</h2>", repl, html)


def markdown_to_html(md: str,
                     brand_title: str = "India Morning Brief",
                     brand_subtitle: Optional[str] = None,
                     kpi_data: Optional[Dict] = None,
                     embed_images: Optional[Dict[str, bytes]] = None,
                     ) -> str:
    """Render markdown to a polished, self-contained HTML document.

    Args:
        md: the markdown brief text
        brand_title: top-of-page heading
        brand_subtitle: small text right of title (e.g. analyst name / firm)
        kpi_data: optional dict for KPI strip:
          {nifty, bn, sensex, fii_net, dii_net, breadth}
        embed_images: dict mapping {IMG:key} placeholders to PNG bytes
    """
    embed_images = embed_images or {}

    # Replace {IMG:key} markers with inline base64 images BEFORE markdown processing.
    def _img_repl(m):
        key = m.group(1)
        b = embed_images.get(key)
        if not b:
            return ""
        return (f'\n\n<div style="text-align:center;margin:16px 0;">'
                f'<img src="{_b64_img(b)}" '
                f'style="max-width:100%;border-radius:8px;'
                f'box-shadow:0 1px 3px rgba(0,0,0,0.06);" /></div>\n\n')
    md_processed = re.sub(r"\{IMG:([^}]+)\}", _img_repl, md)

    # Strip the title H1 — we'll render our own header band
    md_processed = re.sub(r"^#\s+.*$", "", md_processed, count=1, flags=re.M).lstrip()

    # Render markdown
    body_html = md_lib.markdown(md_processed, extensions=["tables", "fenced_code", "nl2br"])
    body_html = _add_section_anchors(body_html)
    body_html = _replace_rec_badges(body_html)

    # Build header + KPI strip
    today_str = date.today().strftime("%A, %d %b %Y")
    subtitle = brand_subtitle or "Institutional Research · Confidential"
    kpi_html = ""
    if kpi_data:
        kpi_html = _kpi_cards_html(
            kpi_data.get("nifty"), kpi_data.get("bn"), kpi_data.get("sensex"),
            kpi_data.get("fii_net"), kpi_data.get("dii_net"),
            kpi_data.get("breadth"),
        )
    nav_html = _section_nav_html(md_processed)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{brand_title} — {today_str}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                         Helvetica, Arial, sans-serif;
            background: {_LIGHT}; color: {_INK};
            margin: 0; padding: 24px;
            line-height: 1.55; font-size: 14px;
        }}
        .container {{ max-width: 920px; margin: 0 auto; }}
        .brand-band {{
            background: linear-gradient(90deg, {_BRAND}, {_BRAND_LIGHT});
            color: white; padding: 22px 28px;
            border-radius: 10px 10px 0 0;
            display: flex; justify-content: space-between; align-items: center;
            flex-wrap: wrap; gap: 12px;
        }}
        .brand-band h1 {{ margin: 0; font-size: 22px; font-weight: 700; letter-spacing: 0.2px; }}
        .brand-band .tag {{
            font-size: 10px; letter-spacing: 1px; opacity: 0.85;
            text-transform: uppercase; margin-top: 4px; font-weight: 600;
        }}
        .brand-band .date {{ font-size: 13px; opacity: 0.95; }}
        .content {{
            background: white; padding: 24px 28px;
            border-radius: 0 0 10px 10px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.04);
        }}
        h2 {{
            font-size: 17px; color: {_BRAND}; margin: 28px 0 8px;
            padding: 6px 0 6px 12px; border-left: 4px solid {_BRAND};
            background: #fafbfd;
        }}
        h3 {{ font-size: 14px; color: {_INK}; margin: 18px 0 6px; }}
        p {{ margin: 8px 0 12px; }}
        ul {{ padding-left: 22px; margin: 8px 0 16px; }}
        li {{ margin: 4px 0; }}
        a {{ color: #0a58ca; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        table {{
            border-collapse: collapse; width: 100%; margin: 12px 0 18px;
            font-size: 13px;
        }}
        th {{
            background: #e8eef5; color: {_INK}; text-align: left;
            padding: 8px 10px; border-bottom: 2px solid {_BORDER};
            font-weight: 600;
        }}
        td {{ padding: 7px 10px; border-bottom: 1px solid {_BORDER}; }}
        tr:nth-child(even) td {{ background: #fafbfc; }}
        code {{
            background: #f1f5f9; padding: 1px 5px; border-radius: 3px;
            font-family: "SF Mono", "Menlo", Consolas, monospace; font-size: 12px;
        }}
        em {{ color: {_MUTED}; }}
        hr {{ border: none; border-top: 1px solid {_BORDER}; margin: 20px 0; }}
        .footer {{
            margin-top: 24px; padding-top: 16px;
            border-top: 1px solid {_BORDER};
            font-size: 11px; color: {_MUTED};
            text-align: center; line-height: 1.6;
        }}
        @media print {{
            body {{ background: white; padding: 0; }}
            .container {{ max-width: none; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="brand-band">
            <div>
                <h1>{brand_title}</h1>
                <div class="tag">Institutional Equity Research · India</div>
            </div>
            <div class="date">{today_str}</div>
        </div>
        <div class="content">
            {kpi_html}
            {nav_html}
            {body_html}
            <div class="footer">
                For institutional use only · Not investment advice · Verify all figures before action<br/>
                Generated {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC by Macro Research Agent
            </div>
        </div>
    </div>
</body>
</html>
"""
