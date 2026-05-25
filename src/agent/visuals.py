"""Visual asset generators for the morning brief PDF + HTML.

All return PNG bytes suitable for embedding. Headless matplotlib (Agg backend)
already set in pdf_export / stock_in_focus.
"""
from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

log = logging.getLogger(__name__)

# Institutional palette
_NAVY = "#0a3d62"
_INK = "#1a1a1a"
_GREEN = "#0a7e2f"
_RED = "#b71c1c"
_AMBER = "#d97706"
_GREY = "#6b7280"
_LIGHT = "#f5f7fa"


def sectoral_heatmap_png(indices: List[Dict[str, Any]]) -> Optional[bytes]:
    """Horizontal bar chart of sectoral % change. `indices` must include sector index rows."""
    sectoral = [i for i in (indices or [])
                if i.get("index") not in ("Nifty 50", "Bank Nifty", "Sensex")
                and i.get("change_pct") is not None]
    if not sectoral:
        return None
    sectoral.sort(key=lambda x: x["change_pct"])
    labels = [i["index"].replace("Nifty ", "") for i in sectoral]
    values = [i["change_pct"] for i in sectoral]
    colors = [_GREEN if v >= 0 else _RED for v in values]

    fig, ax = plt.subplots(figsize=(7.5, max(2.5, 0.32 * len(labels))), dpi=140)
    bars = ax.barh(labels, values, color=colors, alpha=0.85, edgecolor="white", linewidth=0.6)
    ax.axvline(0, color=_INK, linewidth=0.8)
    ax.set_title("Sectoral performance — yesterday close", fontsize=10, color=_INK, loc="left")
    ax.set_xlabel("% change", fontsize=9, color=_GREY)
    ax.tick_params(labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(_GREY)
    ax.spines["bottom"].set_color(_GREY)
    # Value labels at bar end
    for bar, v in zip(bars, values):
        ax.text(v + (0.05 if v >= 0 else -0.05), bar.get_y() + bar.get_height() / 2,
                f"{v:+.2f}%", va="center",
                ha="left" if v >= 0 else "right",
                fontsize=8, color=_INK)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def kpi_strip_png(nifty: Optional[Dict], bn: Optional[Dict], sensex: Optional[Dict],
                  fii_net_cr: Optional[float], dii_net_cr: Optional[float],
                  breadth: Optional[Dict] = None) -> bytes:
    """Wide PNG with KPI cards — for embedding at top of PDF / HTML."""
    fig, ax = plt.subplots(figsize=(8.4, 1.6), dpi=140)
    ax.axis("off")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 10)

    cards = []
    if nifty:
        chg = nifty.get("change_pct", 0)
        cards.append(("NIFTY 50", f"{nifty['close']:,.0f}", f"{chg:+.2f}%",
                      _GREEN if chg >= 0 else _RED))
    if bn:
        chg = bn.get("change_pct", 0)
        cards.append(("BANK NIFTY", f"{bn['close']:,.0f}", f"{chg:+.2f}%",
                      _GREEN if chg >= 0 else _RED))
    if sensex:
        chg = sensex.get("change_pct", 0)
        cards.append(("SENSEX", f"{sensex['close']:,.0f}", f"{chg:+.2f}%",
                      _GREEN if chg >= 0 else _RED))
    if fii_net_cr is not None:
        cards.append(("FII NET (Cr)", f"₹{fii_net_cr:+,.0f}", "Cash mkt",
                      _GREEN if fii_net_cr >= 0 else _RED))
    if dii_net_cr is not None:
        cards.append(("DII NET (Cr)", f"₹{dii_net_cr:+,.0f}", "Cash mkt",
                      _GREEN if dii_net_cr >= 0 else _RED))
    if breadth and breadth.get("adv_dec_ratio") is not None:
        adr = breadth["adv_dec_ratio"]
        cards.append(("A/D RATIO", f"{adr:.2f}",
                      f"{breadth.get('advances',0)} adv / {breadth.get('declines',0)} dec",
                      _GREEN if adr >= 1 else _RED))

    if not cards:
        cards = [("No data", "—", "", _GREY)]

    n = len(cards)
    card_w = 100.0 / n
    pad = 1.0
    for i, (label, value, sub, color) in enumerate(cards):
        x = i * card_w + pad
        w = card_w - 2 * pad
        # Background card
        card = mpatches.FancyBboxPatch(
            (x, 0.5), w, 9,
            boxstyle="round,pad=0.02,rounding_size=0.4",
            linewidth=0.8, edgecolor="#d8dde6", facecolor=_LIGHT,
            transform=ax.transData,
        )
        ax.add_patch(card)
        # Color accent bar on left
        accent = mpatches.Rectangle((x, 0.5), 0.25, 9, color=color)
        ax.add_patch(accent)
        # Label
        ax.text(x + 0.8, 8, label, fontsize=7.5, color=_GREY, weight="bold",
                va="top", transform=ax.transData)
        # Value
        ax.text(x + 0.8, 5.5, value, fontsize=12, color=_INK, weight="bold",
                va="center", transform=ax.transData)
        # Sub-text
        ax.text(x + 0.8, 2.5, sub, fontsize=7.5, color=color, weight="bold",
                va="top", transform=ax.transData)

    fig.tight_layout(pad=0)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white",
                pad_inches=0.05)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def global_cues_strip_png(cues: List[Dict[str, Any]], max_cues: int = 8) -> bytes:
    """Smaller strip for global cues — 1 row of compact cards."""
    cues = (cues or [])[:max_cues]
    fig, ax = plt.subplots(figsize=(8.4, 0.9), dpi=140)
    ax.axis("off")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 10)

    if not cues:
        ax.text(50, 5, "Global cues unavailable", ha="center", color=_GREY)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return buf.getvalue()

    n = len(cues)
    card_w = 100.0 / n
    for i, c in enumerate(cues):
        x = i * card_w + 0.4
        w = card_w - 0.8
        chg = c.get("change_pct", 0)
        color = _GREEN if chg >= 0 else _RED
        ax.text(x + w / 2, 7.5, c.get("cue", ""), fontsize=7, color=_GREY,
                ha="center", weight="bold")
        ax.text(x + w / 2, 4.5, f"{c.get('close', 0):,.1f}", fontsize=9,
                color=_INK, ha="center", weight="bold")
        ax.text(x + w / 2, 1.5, f"{chg:+.2f}%", fontsize=8, color=color,
                ha="center", weight="bold")

    fig.tight_layout(pad=0)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white",
                pad_inches=0.05)
    plt.close(fig)
    return buf.getvalue()
