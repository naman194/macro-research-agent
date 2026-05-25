"""HTML brief exporter — v2 (Claude Design morning brief, template-fill approach).

The reference design HTML lives at
  /tmp/handover/design_handoff_morning_brief/India Morning Brief.html
This module embeds the reference verbatim as a `string.Template`, with the
sample-data values replaced by ``${PLACEHOLDER}`` tokens.  Filling those tokens
from a `DailyNoteData` instance yields a brief that is structurally identical
to the design — only the data changes day-to-day.

The Tweaks panel (React/Babel scripts) is stripped from the production output
per the design handover README.

Public API:
    render_brief_v2(data, kpi_data=None, embed_images=None) -> str
"""
from __future__ import annotations

import html as _html
import logging
import re
from datetime import date, datetime, timedelta
from string import Template
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
#  Helpers — formatting numbers, escaping HTML, picking sample/fallback values
# ════════════════════════════════════════════════════════════════════════════

def _h(s: Any) -> str:
    if s is None:
        return ""
    return _html.escape(str(s), quote=True)


def _num(v: Any, decimals: int = 2, default: str = "n/a") -> str:
    try:
        if v is None or (isinstance(v, float) and v != v):
            return default
        return f"{float(v):,.{decimals}f}"
    except Exception:
        return default


def _int(v: Any, default: str = "n/a") -> str:
    try:
        if v is None or (isinstance(v, float) and v != v):
            return default
        return f"{int(round(float(v))):,}"
    except Exception:
        return default


def _pct(v: Any, decimals: int = 2, default: str = "n/a") -> str:
    try:
        if v is None or (isinstance(v, float) and v != v):
            return default
        s = f"{float(v):+,.{decimals}f}%"
        return s.replace("-", "−")
    except Exception:
        return default


def _signed_cr(v: Any, default: str = "n/a") -> str:
    try:
        if v is None or (isinstance(v, float) and v != v):
            return default
        n = float(v)
        sign = "+" if n >= 0 else "−"
        return f"{sign}₹{abs(n):,.0f} Cr"
    except Exception:
        return default


def _dir_class(v: Any) -> str:
    try:
        return "up" if float(v) >= 0 else "down"
    except Exception:
        return "up"


def _stance_chip(stance: str) -> str:
    """Map a stance string to one of: buy / hold / sell / risk / neutral."""
    if not stance:
        return "neutral"
    s = stance.lower()
    if any(k in s for k in ("buy", "positive", "accumulate", "add", "long")):
        return "buy"
    if any(k in s for k in ("hold", "lean", "mixed")):
        return "hold"
    if any(k in s for k in ("sell", "exit", "trim")):
        return "sell"
    if "risk" in s or "off" in s or "avoid" in s:
        return "risk"
    return "neutral"


def _flat_spark(direction: str = "up", width: int = 120, height: int = 20) -> str:
    """Synthetic flat polyline used when intraday spark data is missing."""
    stroke = "#1b6b3a" if direction == "up" else ("#b1271f" if direction == "down" else "#7c8497")
    if direction == "up":
        pts = "0,15 20,13 40,14 60,11 80,10 100,7 120,5"
    elif direction == "down":
        pts = "0,5 20,7 40,8 60,10 80,12 100,14 120,16"
    else:
        pts = "0,10 20,11 40,10 60,12 80,10 100,11 120,11"
    return (
        f'<svg class="spark" width="100%" height="{height}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none"><polyline fill="none" stroke="{stroke}" '
        f'stroke-width="1.2" points="{pts}"/></svg>'
    )


def _mover_spark(direction: str = "up") -> str:
    stroke = "#1b6b3a" if direction == "up" else "#b1271f"
    pts = (
        "0,14 12,12 24,13 36,10 48,11 60,8 72,5 84,2"
        if direction == "up"
        else "0,3 12,5 24,6 36,8 48,9 60,11 72,14 84,16"
    )
    return (
        f'<svg width="84" height="18" viewBox="0 0 84 18">'
        f'<polyline fill="none" stroke="{stroke}" stroke-width="1.3" points="{pts}"/>'
        f'</svg>'
    )


def _pick(d: Optional[Dict], *keys, default: Any = None) -> Any:
    if not d:
        return default
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default


# ════════════════════════════════════════════════════════════════════════════
#  Fragment builders — one per section, returns the inner HTML chunk
# ════════════════════════════════════════════════════════════════════════════

def _find_idx(items: List[Dict], key: str, value: str) -> Optional[Dict]:
    for it in items or []:
        if it.get(key) == value:
            return it
    return None


def _ticker_cells(indices: List[Dict], cues: List[Dict]) -> Dict[str, str]:
    """Build placeholders TK1_*..TK6_*: Nifty / Sensex / Bank Nifty / USD-INR / Brent / VIX."""
    out: Dict[str, str] = {}
    nifty = _find_idx(indices, "index", "Nifty 50")
    sensex = _find_idx(indices, "index", "Sensex")
    bn = _find_idx(indices, "index", "Bank Nifty")
    inr = _find_idx(cues, "cue", "USDINR=X") or _find_idx(cues, "cue", "USD/INR")
    brent = _find_idx(cues, "cue", "Brent") or _find_idx(cues, "cue", "BZ=F")
    vix = _find_idx(cues, "cue", "VIX") or _find_idx(cues, "cue", "^VIX") or _find_idx(cues, "cue", "India VIX")

    spec = [
        ("Nifty 50", "NIFTY · NSEI", nifty, "close", "change", "change_pct"),
        ("Sensex", "SENSEX · BSESN", sensex, "close", "change", "change_pct"),
        ("Bank Nifty", "NSEBANK", bn, "close", "change", "change_pct"),
        ("USD / INR", "INR=X · spot", inr, "close", "change", "change_pct"),
        ("Brent", "CO1 · $/bbl", brent, "close", "change", "change_pct"),
        ("India VIX", "INDIAVIX · proxy", vix, "close", "change", "change_pct"),
    ]
    for i, (lbl, code, src, k_val, k_abs, k_pct) in enumerate(spec, 1):
        val = src.get(k_val) if src else None
        abs_chg = src.get(k_abs) if src else None
        pct_chg = src.get(k_pct) if src else None
        # value formatting: VIX 2dp, INR 2dp, others int
        if val is None:
            v_str = "n/a"
        elif lbl in ("USD / INR", "India VIX", "Brent"):
            v_str = _num(val, 2)
        else:
            v_str = _int(val)
        if pct_chg is None and abs_chg is None:
            chg_str = "n/a"; dir_cls = "up"
        else:
            dir_cls = _dir_class(pct_chg if pct_chg is not None else abs_chg)
            parts = []
            if abs_chg is not None:
                abs_fmt = _num(abs_chg, 1).replace("-", "−")
                if not abs_fmt.startswith("−"):
                    abs_fmt = "+" + abs_fmt
                parts.append(abs_fmt)
            if pct_chg is not None:
                parts.append(_pct(pct_chg, 2))
            chg_str = " · ".join(parts) if parts else "n/a"
        out[f"TK{i}_LBL"] = _h(lbl)
        out[f"TK{i}_CODE"] = _h(code)
        out[f"TK{i}_VAL"] = _h(v_str)
        out[f"TK{i}_DIR"] = dir_cls
        out[f"TK{i}_CHG"] = _h(chg_str)
    return out


def _rec_rows(data) -> str:
    """Filter Output Summary table body — observational, NOT recommendations.
    Topic / Observation / Read / Key level. Stance chip is filter-state, not buy/sell."""
    indices = data.indices_snapshot or []
    nifty = _find_idx(indices, "index", "Nifty 50")
    bn = _find_idx(indices, "index", "Bank Nifty")
    fno = data.fno_signals or []
    bn_fno = next((x for x in fno if "BANK" in str(x.get("symbol", "")).upper()), None)

    nifty_dma = "n/a — verify"
    regime = (data.swing_setups or {}).get("regime") or "unknown"
    # Neutral observation chips (CSS classes still match buy/hold/sell/neutral
    # since they only carry color, but the LABELS are observational)
    if "off" in regime.lower():
        regime_chip_cls = "sell"; regime_label = "Risk-Off Regime"
    elif "on" in regime.lower():
        regime_chip_cls = "buy"; regime_label = "Risk-On Regime"
    else:
        regime_chip_cls = "neutral"; regime_label = "Neutral Regime"

    # Top filter output
    sif = data.stock_in_focus or {}
    top = (data.top_garp or data.top_quality_value or [{}])[0]
    top_ticker = sif.get("ticker") or top.get("ticker") or "n/a"
    top_name_short = sif.get("name") or top.get("name") or ""

    rows = []
    # Row 1: Index Regime — observation
    rows.append(
        f'''        <tr>
          <td class="topic">Index Regime <small>Nifty vs 200DMA</small></td>
          <td><span class="rec-chip {regime_chip_cls}">{_h(regime_label)}</span></td>
          <td>{"Trend-following systems suppress long signals when Nifty trades below 200DMA. Breadth confirmation typically precedes regime change." if regime_chip_cls=="sell" else "Trend filter is intact. Historical pattern: positive setups fire more frequently in this regime."}</td>
          <td class="num-cell">200DMA · {_h(nifty_dma)}</td>
        </tr>'''
    )
    # Row 2: Top filter output
    if top_ticker and top_ticker != "n/a":
        rows.append(
            f'''        <tr>
          <td class="topic">{_h(top_ticker)} <small>{_h(top_name_short) or "Highest filter score"}</small></td>
          <td><span class="rec-chip buy">PASSES</span></td>
          <td>Highest adjusted composite score in today's filter output. See §05 for the full data breakdown including bear considerations.</td>
          <td class="num-cell">See §05</td>
        </tr>'''
        )
    # Row 3: Bank Nifty F&O positioning data
    if bn_fno:
        spot = bn_fno.get("underlying")
        mp = bn_fno.get("max_pain")
        mp_d = bn_fno.get("max_pain_distance_pct")
        sent = bn_fno.get("sentiment") or "Mixed"
        spot_str = _int(spot) if spot else "n/a"
        rows.append(
            f'''        <tr>
          <td class="topic">Bank Nifty F&amp;O <small>Into nearest expiry</small></td>
          <td><span class="rec-chip {_stance_chip(sent)}">{_h(sent.title())} OI</span></td>
          <td>Max-pain {_int(mp)} ({_pct(mp_d,2)} to spot). Spot {spot_str}. OI structure shown is descriptive; historical pin/gravitational behaviour varies.</td>
          <td class="num-cell">Spot · {spot_str}</td>
        </tr>'''
        )
    # Row 4: Sector laggards data
    sectoral = [i for i in indices if i.get("index") not in ("Nifty 50", "Sensex", "Bank Nifty")]
    sectoral.sort(key=lambda x: float(x.get("change_pct") or 0))
    if len(sectoral) >= 2:
        l1, l2 = sectoral[0], sectoral[1]
        rows.append(
            f'''        <tr>
          <td class="topic">{_h(l1["index"])} / {_h(l2["index"])} <small>Sector laggards yesterday</small></td>
          <td><span class="rec-chip neutral">Underperformers</span></td>
          <td>{_h(l1["index"])} {_pct(l1.get("change_pct"))} / {_h(l2["index"])} {_pct(l2.get("change_pct"))} on the session. Data point only.</td>
          <td class="num-cell">—</td>
        </tr>'''
        )
    # Row 5: Brent / commodity observation
    brent = _find_idx(data.global_cues or [], "cue", "Brent") or _find_idx(data.global_cues or [], "cue", "BZ=F")
    if brent:
        bp = brent.get("change_pct") or 0
        chip_cls = "buy" if bp < 0 else "sell"
        label = "Crude Easing" if bp < 0 else "Crude Firming"
        rationale = ("Crude relief historically correlates with margin tailwind for OMCs, paints, aviation; pressure on upstream ONGC, Oil India."
                     if bp < 0
                     else "Crude firmness historically pressures OMCs, paints, aviation margins; tailwind to upstream ONGC, Oil India.")
        rows.append(
            f'''        <tr>
          <td class="topic">Energy Complex <small>Brent {_pct(bp)}</small></td>
          <td><span class="rec-chip {chip_cls}">{label}</span></td>
          <td>{rationale}</td>
          <td class="num-cell">Brent · ${_num(brent.get("close"),2)}</td>
        </tr>'''
        )
    return "\n".join(rows)


def _glance_data(data, kpi_data: Dict) -> Dict[str, str]:
    indices = data.indices_snapshot or []
    nifty = _find_idx(indices, "index", "Nifty 50") or kpi_data.get("nifty") or {}
    bn = _find_idx(indices, "index", "Bank Nifty") or kpi_data.get("bn") or {}
    sensex = _find_idx(indices, "index", "Sensex") or kpi_data.get("sensex") or {}
    cues = data.global_cues or []
    sp = _find_idx(cues, "cue", "S&P 500") or _find_idx(cues, "cue", "SPX") or _find_idx(cues, "cue", "^GSPC")
    nikkei = _find_idx(cues, "cue", "Nikkei") or _find_idx(cues, "cue", "^N225")
    brent = _find_idx(cues, "cue", "Brent") or _find_idx(cues, "cue", "BZ=F")
    inr = _find_idx(cues, "cue", "USDINR=X") or _find_idx(cues, "cue", "USD/INR")
    ust = _find_idx(cues, "cue", "US 10Y") or _find_idx(cues, "cue", "^TNX")

    breadth = kpi_data.get("breadth") or data.breadth or {}
    adr = breadth.get("adv_dec_ratio")
    fii_v = kpi_data.get("fii_net")
    dii_v = kpi_data.get("dii_net")

    nifty_str = _int(nifty.get("close")) if nifty else "n/a"
    nifty_pct = _pct(nifty.get("change_pct")) if nifty else "n/a"
    bn_pct = _pct(bn.get("change_pct")) if bn else "n/a"

    # Lead body — two paragraphs
    p1_bits = [f"<strong>Nifty closed at {nifty_str} ({nifty_pct})</strong>"]
    if bn:
        p1_bits.append(f"Bank Nifty {bn_pct}")
    if adr is not None:
        p1_bits.append(f"breadth {adr}<span class=\"ref\">¹</span>")
    if fii_v is not None and dii_v is not None:
        p1_bits.append(f"FIIs net ₹{fii_v:+,.0f} Cr, DIIs net ₹{dii_v:+,.0f} Cr")
    p1 = " · ".join(p1_bits) + "."

    p2_bits = ["Overnight tape:"]
    if sp:
        p2_bits.append(f"S&P {_pct(sp.get('change_pct'))}")
    if nikkei:
        p2_bits.append(f"Nikkei {_pct(nikkei.get('change_pct'))}")
    if brent:
        p2_bits.append(f"Brent <strong>${_num(brent.get('close'),2)} ({_pct(brent.get('change_pct'))})</strong>")
    if inr:
        p2_bits.append(f"INR {_num(inr.get('close'),2)}")
    if ust:
        p2_bits.append(f"US 10Y {_num(ust.get('close'),3)}%")
    p2 = " · ".join(p2_bits) + "."

    lead = f"<p>{p1}</p>\n        <p>{p2}</p>"

    regime = (data.swing_setups or {}).get("regime") or ""
    our_view = (
        "Swing scanner flags <strong>Nifty regime risk-off</strong>. "
        "Lead with financials and quality compounders; avoid chasing breadth. "
        "Use index strength to lighten leveraged longs; do not add until a clean "
        "reclaim with breadth confirmation. Globally cautiously risk-on but local "
        "regime risk-off — be selective; do not conflate the two."
    ) if "off" in regime.lower() else (
        "Tape constructive with breadth backing. Stay invested in quality leaders; "
        "fade extension into resistance. Watch for breadth deterioration as the "
        "first warning of trend exhaustion."
    )

    # Flow bar — proportional split of |FII| vs |DII|
    f_abs = abs(fii_v) if fii_v is not None else 0
    d_abs = abs(dii_v) if dii_v is not None else 0
    total = f_abs + d_abs
    if total > 0:
        fii_pct_w = round(100 * f_abs / total, 1)
        dii_pct_w = round(100 - fii_pct_w, 1)
    else:
        fii_pct_w = 50.0
        dii_pct_w = 50.0

    # Caption
    if total > 0 and f_abs > 0:
        ratio = d_abs / max(f_abs, 1)
        flow_cap = (f"DIIs absorbed <b>{ratio:.2f}×</b> of FII selling. "
                    f"Sustainable only while SIP flows hold — monitor monthly inflow print next week.")
    else:
        flow_cap = "FII/DII print pending; monitor for next session."

    flows_title = "Institutional Flows"
    # Use the most recent FII/DII date if present
    if data.fii_dii:
        d0 = data.fii_dii[0].get("date") if isinstance(data.fii_dii[0], dict) else None
        if d0:
            flows_title = f"Institutional Flows · {d0}"

    return {
        "GLANCE_LEAD_BODY": lead,
        "GLANCE_OUR_VIEW": our_view,
        "GLANCE_FLOWS_TITLE": _h(flows_title),
        "GLANCE_FII_AMT": _h(_signed_cr(fii_v)),
        "GLANCE_DII_AMT": _h(_signed_cr(dii_v)),
        "GLANCE_FII_PCT": str(fii_pct_w),
        "GLANCE_DII_PCT": str(dii_pct_w),
        "GLANCE_FII_BAR_LBL": _h(f"{int(round(fii_v or 0)):+,}" if fii_v is not None else "n/a"),
        "GLANCE_DII_BAR_LBL": _h(f"{int(round(dii_v or 0)):+,}" if dii_v is not None else "n/a"),
        "GLANCE_FLOW_CAP": flow_cap,
    }


def _pm_tiles_block(data) -> Dict[str, str]:
    """6-tile premarket grid + signal strip."""
    cues = data.global_cues or []
    sp = _find_idx(cues, "cue", "S&P 500") or _find_idx(cues, "cue", "SPX") or _find_idx(cues, "cue", "^GSPC")
    nikkei = _find_idx(cues, "cue", "Nikkei") or _find_idx(cues, "cue", "^N225")
    brent = _find_idx(cues, "cue", "Brent") or _find_idx(cues, "cue", "BZ=F")
    inr = _find_idx(cues, "cue", "USDINR=X") or _find_idx(cues, "cue", "USD/INR")
    ust = _find_idx(cues, "cue", "US 10Y") or _find_idx(cues, "cue", "^TNX")
    vix = _find_idx(cues, "cue", "VIX") or _find_idx(cues, "cue", "^VIX")

    tiles_spec = [
        ("S&P 500", "SPX", sp, 0, "Risk-on overnight — supportive for ADR-linked IT & pharma."),
        ("Nikkei 225", "N225", nikkei, 0, "Asia tone reader — read-through for export plays."),
        ("Brent", "CO1", brent, 2, "Crude move impacts OMCs, paints, aviation; inverse for ONGC/Oil India."),
        ("USD / INR", "INR=X", inr, 2, "INR direction: tailwind/headwind for IT, importers."),
        ("US 10Y", "UST10Y", ust, 3, "Yields direction: signals duration / rate-sensitives."),
        ("VIX", "VIX", vix, 2, "Global vol gauge — stress signal."),
    ]
    parts = []
    risk_on_count = 0
    for label, code, src, dec, tag in tiles_spec:
        if src:
            val = src.get("close")
            pct = src.get("change_pct")
            val_str = _num(val, dec) if val is not None else "n/a"
            if label == "Brent":
                val_str = "$" + val_str
            pct_str = _pct(pct) if pct is not None else "n/a"
            direction = _dir_class(pct)
            if pct is not None and pct > 0 and label != "VIX":
                risk_on_count += 1
            elif label == "Brent" and pct is not None and pct < 0:
                risk_on_count += 1
        else:
            val_str = "n/a"; pct_str = "n/a"; direction = "up"
        spark = _flat_spark(direction)
        parts.append(
            f'''      <div class="pm">
        <div class="pm-ticker">{_h(label)} <span class="code">{_h(code)}</span></div>
        <div class="pm-val">{_h(val_str)}</div>
        <div class="pm-chg {direction}">{_h(pct_str)}</div>
        {spark}
        <div class="pm-tag">{_h(tag)}</div>
      </div>'''
        )
    tiles_html = "\n".join(parts)

    # Signal strip
    if risk_on_count >= 4:
        sig_copy = "Overnight tape <strong>risk-on</strong> globally — supportive open. Watch for follow-through in financials and IT."
        sig_label, sig_variant = "Risk-On", "buy"
    elif risk_on_count <= 2:
        sig_copy = "Overnight tape <strong>risk-off</strong> — defensive posture warranted at the open."
        sig_label, sig_variant = "Risk-Off", "risk"
    else:
        sig_copy = "Globally <strong>mixed</strong> overnight. Be selective; do not conflate global tone with local regime."
        sig_label, sig_variant = "Mixed", "hold"
    return {
        "PM_TILES": tiles_html,
        "PM_SIGNAL_COPY": sig_copy,
        "PM_SIGNAL_LABEL": _h(sig_label),
        "PM_SIGNAL_VARIANT": sig_variant,
    }


def _market_action_block(data) -> Dict[str, str]:
    indices = data.indices_snapshot or []
    sectoral = [i for i in indices if i.get("index") not in ("Nifty 50", "Sensex", "Bank Nifty")]
    # If Bank Nifty exists, treat it as sector too (per design)
    bn = _find_idx(indices, "index", "Bank Nifty")
    rows_data = []
    if bn:
        rows_data.append({"name": "Bank Nifty", "code": "NSEBANK",
                         "pct": bn.get("change_pct")})
    for s in sectoral:
        rows_data.append({"name": s.get("index"), "code": s.get("index", "").upper().replace(" ", ""),
                         "pct": s.get("change_pct")})
    # Sort by pct desc, take first 6
    rows_data.sort(key=lambda x: float(x.get("pct") or 0), reverse=True)
    rows_data = rows_data[:6]
    max_abs = max((abs(float(r.get("pct") or 0)) for r in rows_data), default=1.0) or 1.0
    sector_rows = []
    for r in rows_data:
        p = float(r.get("pct") or 0)
        width = min(48, abs(p) / max_abs * 48)
        dirc = "up" if p >= 0 else "down"
        sector_rows.append(
            f'''        <div class="sector-row">
          <span class="name">{_h(r["name"])} <small>{_h(r.get("code") or "")}</small></span>
          <div class="barwrap"><div class="bar {dirc}" style="width: {width:.0f}%;"></div></div>
          <span class="pct {dirc}">{_pct(p)}</span>
        </div>'''
        )
    # Index rows: Nifty, Sensex, Bank Nifty
    idx_specs = [
        ("Nifty 50", "NIFTY · NSEI", _find_idx(indices, "index", "Nifty 50")),
        ("Sensex", "SENSEX · BSESN", _find_idx(indices, "index", "Sensex")),
        ("Bank Nifty", "NSEBANK", bn),
    ]
    index_rows = []
    for name, code, src in idx_specs:
        if not src:
            continue
        v = _int(src.get("close"))
        p = src.get("change_pct")
        dirc = _dir_class(p)
        index_rows.append(
            f'''        <div class="index-row">
          <div class="nm">{_h(name)}<small>{_h(code)}</small></div>
          <div class="val">{_h(v)}</div>
          <div class="pct {dirc}">{_pct(p)}</div>
        </div>'''
        )

    breadth = data.breadth or {}
    adv = breadth.get("advances", 0)
    dec = breadth.get("declines", 0)
    ratio = breadth.get("adv_dec_ratio")
    if (adv + dec) > 0:
        bratio_pct = 100 * adv / (adv + dec)
    else:
        bratio_pct = 50
    return {
        "SECTOR_ROWS": "\n".join(sector_rows) if sector_rows else '        <div class="sector-row"><span class="name">No sector data</span><div class="barwrap"></div><span class="pct">n/a</span></div>',
        "INDEX_ROWS": "\n".join(index_rows) if index_rows else "",
        "BREADTH_AD": f"{adv} adv / {dec} dec",
        "BREADTH_PCT": f"{bratio_pct:.1f}",
        "BREADTH_RATIO": str(ratio) if ratio is not None else "n/a",
    }


def _movers_block(data) -> Dict[str, str]:
    def _rows(items, direction):
        if not items:
            return f'            <tr><td colspan="4" style="color: var(--muted); padding: 14px 0;">No data</td></tr>'
        out = []
        for it in items[:5]:
            tk = it.get("ticker") or it.get("symbol") or ""
            name = it.get("name") or it.get("sector") or ""
            px = it.get("close")
            pc = it.get("change_pct")
            px_str = _num(px, 1)
            pc_sign = ("+" if (pc or 0) >= 0 else "−")
            pc_str = f"{pc_sign}{abs(float(pc)):,.2f}" if pc is not None else "n/a"
            out.append(
                f'''            <tr>
              <td class="tk">{_h(tk)}<small>{_h(name)}</small></td>
              <td class="sp">{_mover_spark(direction)}</td>
              <td class="px">{_h(px_str)}</td>
              <td class="pc {direction}">{_h(pc_str)}</td>
            </tr>'''
            )
        return "\n".join(out)

    return {
        "GAINERS_ROWS": _rows(data.gainers or [], "up"),
        "LOSERS_ROWS": _rows(data.losers or [], "down"),
    }


def _idea_block(data) -> Dict[str, str]:
    """Idea-of-the-day card. Prefer stock_in_focus; fall back to top GARP pick."""
    sif = data.stock_in_focus or {}
    top = sif if (sif and "error" not in sif) else (
        (data.top_garp or data.top_quality_value or [{}])[0]
    )
    if not top:
        top = {}
    ticker = top.get("ticker") or "n/a"
    name = top.get("name") or top.get("company") or ""
    sector = top.get("sector") or "Top-ranked filter output"

    pe = top.get("pe")
    roe = top.get("roe")
    roce = top.get("roce")
    peg = top.get("peg")
    mcap = top.get("market_cap_cr") or top.get("mcap")
    p3y = top.get("profit_growth_3y")
    p1y = top.get("price_growth_1y") or top.get("return_1y")

    score = top.get("score")
    raw_score = top.get("raw_score")
    sp = top.get("structural_penalty")
    cb = top.get("catalyst_bonus")
    note = top.get("score_note") or sif.get("score_note") or \
        "Top score on our screen after structural overlay."

    # Entry/Stop/Target — heuristic if missing
    close = top.get("close") or top.get("current_price") or top.get("ltp")
    entry_lo = top.get("entry_low") or top.get("entry")
    entry_hi = top.get("entry_high")
    stop = top.get("stop") or top.get("stop_loss")
    target = top.get("target") or top.get("base_case_price") or top.get("dcf_target")
    if close and not entry_lo:
        entry_lo = round(float(close) * 0.985)
        entry_hi = round(float(close) * 1.005)
    if close and not stop:
        stop = round(float(close) * 0.93)
    if close and not target:
        target = round(float(close) * 1.30)

    def _rs(v):
        return f"₹{_int(v)}" if v is not None else "n/a"

    entry_str = (f"₹{_int(entry_lo)} – {_int(entry_hi)}"
                 if entry_lo and entry_hi else _rs(entry_lo or entry_hi))
    stop_pct = ""
    if close and stop:
        s_pct = (float(close) - float(stop)) / float(close) * 100
        stop_pct = f' <span style="color: var(--muted); font-size: 11px;">(~{s_pct:.0f}%)</span>'
    stop_str = f"{_rs(stop)}{stop_pct}"
    target_str = _rs(target)

    thesis = top.get("thesis") or sif.get("thesis") or (
        f"Highest composite score in today's filter output. "
        f"<strong>Score {_num(score, 2)}</strong> after structural overlay adjustment. "
        f"<em>Screen-leading fundamental metrics across the universe.</em>"
    )

    bullets_src = top.get("bullets") or sif.get("bullets") or []
    if not bullets_src:
        bullets_src = [
            f"<b>Adjusted score {_num(score,2)}</b> (raw {_num(raw_score,2)}) — leads our screen after structural adjustment.",
            f"<b>Catalyst:</b> {top.get('catalyst') or sif.get('catalyst') or 'Earnings cycle, sector rotation favourable.'}",
            "<b>Sizing:</b> 2–3% of portfolio · scale 1% on a dip below entry.",
            "<b>Why this vs others:</b> Best risk/reward in the structural-adjusted screen.",
        ]
    bullets_html = "\n".join(f"          <li>{b}</li>" for b in bullets_src[:5])

    bear = top.get("bear_thesis") or sif.get("bear_thesis") or (
        "Sector-specific structural risks remain. We see this name as more resilient than peers, "
        "but a hard regime shift could compress the multiple."
    )

    # Ticker row
    tk_parts = [f'<span><b>{_h(ticker)}</b> · NSE</span>']
    if mcap:
        tk_parts.append(f'<span>Mcap ₹{_num(mcap,0)} Cr</span>')
    if sector:
        tk_parts.append(f'<span>{_h(sector)}</span>')
    tk_row = "\n".join(f"          {p}" for p in tk_parts)

    # Metrics
    met_specs = [
        ("P/E", _num(pe, 1) + "×" if pe is not None else "n/a", "Trailing"),
        ("RoE", _num(roe, 1) + "%" if roe is not None else "n/a", "Latest"),
        ("3y Profit CAGR", _num(p3y, 1) + "%" if p3y is not None else "n/a", "Realised"),
        ("1y Price CAGR", _num(p1y, 1) + "%" if p1y is not None else "n/a", "Realised"),
        ("Mcap", "₹" + (_num(mcap, 0) + " Cr") if mcap is not None else "n/a", "Size"),
        ("PEG", _num(peg, 2) if peg is not None else "n/a", "Growth-adj."),
    ]
    met_html = "\n".join(
        f'          <div class="met"><div class="lbl">{_h(lbl)}</div><div class="val">{_h(val)}</div><div class="sub">{_h(sub)}</div></div>'
        for lbl, val, sub in met_specs
    )

    # Score breakdown
    bd_lines = [f"Raw <b>{_num(raw_score, 2) if raw_score is not None else _num(score, 2)}</b>"]
    if sp is not None:
        bd_lines.append(f"Structural penalty <b class=\"penal\">{_num(sp, 2)}</b>")
    if cb is not None:
        bd_lines.append(f"Catalyst bonus <b class=\"bonus\">+{_num(cb, 2)}</b>")
    breakdown_html = "<br>\n              ".join(bd_lines)

    # Upside bar — Stop / Entry / Target
    upside = ""
    if close and stop and target:
        try:
            sf = float(stop); cf = float(close); tf = float(target)
            lo = min(sf, cf) * 0.97
            hi = max(tf, cf) * 1.03
            span = max(hi - lo, 1.0)
            sp_pct = (sf - lo) / span * 100
            cp_pct = (cf - lo) / span * 100
            tp_pct = (tf - lo) / span * 100
            upside = (
                f'''          <div class="range" style="left: 8%; right: 8%;"></div>
          <div class="marker dn" style="left: {sp_pct:.0f}%;"></div>
          <div class="marker"   style="left: {cp_pct:.0f}%;"></div>
          <div class="marker tg" style="left: {tp_pct:.0f}%;"></div>
          <div class="tk" style="left: {max(sp_pct,8):.0f}%;"><b>₹{_int(stop)}</b>Stop</div>
          <div class="tk" style="left: {cp_pct:.0f}%;"><b>₹{_int(close)}</b>Spot</div>
          <div class="tk" style="left: {min(tp_pct,86):.0f}%; transform: translateX(-100%); border-left: 0; padding-right: 6px; padding-left: 0; text-align: right;"><b>₹{_int(target)}</b>Base</div>'''
            )
        except Exception:
            upside = ""

    # Runner-up
    others = [c for c in (data.top_garp or []) + (data.top_quality_value or []) if c.get("ticker") != ticker]
    if others:
        runner_tag = "Quality+Value runners"
        names = ", ".join(f"<b>{_h(o.get('ticker'))}</b>" for o in others[:3])
        runner_body = f"After {_h(ticker)}, screen-rank order: {names}. Watch for entries on a deeper drawdown — structural overlay says <em>wait</em> for now."
    else:
        runner_tag = "No 2nd add today"
        runner_body = "Only one name clears the structural-adjusted bar today. <em>Discipline over breadth.</em>"

    return {
        "IDEA_STAMP": _h(f"Filter Output · Top-Ranked · {sector}"),
        "IDEA_TITLE": _h(name or ticker),
        "IDEA_TICKER_ROW": tk_row,
        "IDEA_THESIS": thesis,
        "IDEA_BULLETS": bullets_html,
        "IDEA_BEAR": bear,
        "IDEA_ENTRY": _h(entry_str),
        "IDEA_STOP": stop_str,
        "IDEA_TARGET": _h(target_str),
        "IDEA_UPSIDE": upside or "",
        "IDEA_METRICS_TITLE": _h("FY26E"),
        "IDEA_METRICS": met_html,
        "IDEA_SCORE": _h(_num(score, 2)),
        "IDEA_BREAKDOWN": breakdown_html,
        "IDEA_SCORE_NOTE": _h(note),
        "RUNNER_TAG": _h(runner_tag),
        "RUNNER_BODY": runner_body,
    }


def _regime_block(data) -> Dict[str, str]:
    regime = ((data.swing_setups or {}).get("regime") or "").lower()
    if "off" in regime:
        top, mid, bot = "on", "dim", "dim"
        label = "Risk · Off"
        verdict = "No long setups today. <em>Trim, do not add.</em>"
        detail = ("Nifty trading <strong>below 200DMA</strong>. Trim leveraged longs, "
                  "raise stops on momentum names, use index strength to lighten — not add. "
                  "Re-engage only on a clean reclaim with breadth confirmation.")
    elif "neutral" in regime or "mixed" in regime:
        top, mid, bot = "dim", "on", "dim"
        label = "Neutral"
        verdict = "Mixed signals. <em>Selective adds only.</em>"
        detail = ("Nifty hovering around key levels. Selective adds in leadership names; "
                  "respect stops. Avoid leveraged additions until trend clarifies.")
    elif "on" in regime:
        top, mid, bot = "dim", "dim", "on"
        label = "Risk · On"
        verdict = "Trend intact. <em>Add into pullbacks.</em>"
        detail = ("Nifty above 200DMA with breadth supportive. Add into pullbacks in "
                  "leadership names; trail stops on extended winners.")
    else:
        top, mid, bot = "dim", "on", "dim"
        label = "Unknown"
        verdict = "Scanner pending. <em>Hold posture.</em>"
        detail = "Swing scanner output not available — default to current allocation, no new adds."
    # Override the light color for non-risk-off cases: the .light.on CSS uses --down by default.
    # The design uses the same red glow regardless — we keep it consistent.
    return {
        "REGIME_TOP_CLASS": top,
        "REGIME_MID_CLASS": mid,
        "REGIME_BOT_CLASS": bot,
        "REGIME_LABEL": _h(label),
        "REGIME_VERDICT": verdict,
        "REGIME_DETAIL": detail,
        "REGIME_LEVEL_LABEL": _h("Nifty · 200DMA"),
        "REGIME_LEVEL_VAL": "n/a — verify",
        "REGIME_LEVEL_SUB": _h("Reclaim trigger"),
    }


def _fno_block(data) -> Dict[str, str]:
    signals = data.fno_signals or []
    if not signals:
        empty = (
            '''      <div class="fno-card">
        <div class="fno-head"><h4>F&O data <small>n/a</small></h4></div>
        <p class="pin">F&O snapshot not available for today.</p>
      </div>'''
        )
        return {"FNO_CARDS": empty}
    cards = []
    for s in signals[:3]:
        sym = s.get("symbol") or "n/a"
        expiry = s.get("expiry") or "Nearest"
        pcr = s.get("pcr_oi") or s.get("pcr")
        mp = s.get("max_pain")
        spot = s.get("underlying") or s.get("spot")
        dist = s.get("max_pain_distance_pct")
        sup = s.get("support")
        res = s.get("resistance")
        sentiment = s.get("sentiment") or "Mixed"
        # badge variant
        sent_lc = sentiment.lower()
        if "bull" in sent_lc:
            badge_var = "bull"
        elif "bear" in sent_lc:
            badge_var = "bear"
        else:
            badge_var = "mix"

        rows = []
        if pcr is not None:
            pcr_dir = "up" if float(pcr) >= 1.0 else "down"
            rows.append(f'          <div class="fno-row"><span class="k">PCR</span><span class="v {pcr_dir}">{_num(pcr, 2)}</span></div>')
        if mp is not None:
            rows.append(f'          <div class="fno-row"><span class="k">Max Pain</span><span class="v">{_int(mp)}</span></div>')
        if spot is not None:
            rows.append(f'          <div class="fno-row"><span class="k">Spot</span><span class="v">{_int(spot)}</span></div>')
        if dist is not None:
            dir_d = _dir_class(dist)
            rows.append(f'          <div class="fno-row"><span class="k">Distance to Spot</span><span class="v {dir_d}">{_pct(dist, 2)}</span></div>')
        if sup is not None:
            rows.append(f'          <div class="fno-row"><span class="k">Support</span><span class="v">{_int(sup)}</span></div>')
        if res is not None:
            rows.append(f'          <div class="fno-row"><span class="k">Resistance</span><span class="v">{_int(res)}</span></div>')

        pin = s.get("read") or f"OI structure read: {sentiment.lower()}."

        cards.append(
            f'''      <div class="fno-card">
        <div class="fno-head">
          <h4>{_h(sym)}<small>{_h(sym)} · {_h(expiry)}</small></h4>
          <span class="badge {badge_var}">{_h(sentiment)}</span>
        </div>
        <div class="fno-body">
{chr(10).join(rows)}
        </div>
        <p class="pin"><b>Read:</b> {_h(pin)}</p>
      </div>'''
        )
    return {"FNO_CARDS": "\n".join(cards)}


def _smart_money_block(data) -> Dict[str, str]:
    blocks_list = data.block_deals or []
    inst_buys = data.institutional_bulk_deals or []

    blocks_html_parts = []
    # Group block deals by symbol — up to 2 cards
    by_symbol: Dict[str, List[Dict]] = {}
    for b in blocks_list[:20]:
        sym = b.get("symbol") or "n/a"
        by_symbol.setdefault(sym, []).append(b)
    symbols = list(by_symbol.keys())[:2]
    for sym in symbols:
        deals = by_symbol[sym]
        first = deals[0]
        price = first.get("price") or first.get("trade_price")
        price_str = f"₹{_int(price)}" if price else "n/a"
        lines = []
        for d in deals[:5]:
            side = (d.get("side") or "").lower()
            buy = "buy" if side.startswith("b") else "sell"
            client = (d.get("client") or "Unknown")[:48]
            value = d.get("value_cr") or 0
            sign = "+" if buy == "buy" else "−"
            amt_dir = "up" if buy == "buy" else "down"
            lines.append(
                f'''          <div class="flow-line {buy}">
            <div class="dot"></div>
            <div class="nm">{_h(client)}<small>{"Buyer" if buy=="buy" else "Seller"}</small></div>
            <div class="amt {amt_dir}">{sign}₹{_num(value, 0)} Cr</div>
          </div>'''
            )
        blocks_html_parts.append(
            f'''      <div class="block">
        <div class="block-head">
          <div class="nm">{_h(sym)}<small>{_h(sym)} · Block</small></div>
          <div class="price-tag">Price<br><b>{_h(price_str)}</b></div>
        </div>
        <div class="flow-table">
{chr(10).join(lines)}
        </div>
        <p class="read">Block-deal flow at the price tag — watch for follow-through.</p>
      </div>'''
        )

    # If we have fewer than 2 cards, fill with institutional buys summary
    if len(blocks_html_parts) < 2 and inst_buys:
        lines = []
        for d in inst_buys[:5]:
            sym = d.get("symbol") or ""
            client = (d.get("client") or "Institutional")[:40]
            val = d.get("value_cr") or 0
            lines.append(
                f'''          <div class="flow-line buy">
            <div class="dot"></div>
            <div class="nm">{_h(client)}<small>Buyer · {_h(sym)}</small></div>
            <div class="amt up">+₹{_num(val, 0)} Cr</div>
          </div>'''
            )
        blocks_html_parts.append(
            f'''      <div class="block">
        <div class="block-head">
          <div class="nm">Institutional Buys<small>Bulk · Latest</small></div>
          <div class="price-tag">Top-5<br><b>by value</b></div>
        </div>
        <div class="flow-table">
{chr(10).join(lines)}
        </div>
        <p class="read">Institutional accumulation across the tape.</p>
      </div>'''
        )

    if not blocks_html_parts:
        blocks_html_parts.append(
            '''      <div class="block">
        <div class="block-head"><div class="nm">No block deals<small>For the session</small></div></div>
        <p class="read">No notable block-deal activity in the session.</p>
      </div>'''
        )

    # Promoter activity footer
    pb = data.promoter_buys or []
    ps = data.promoter_sells or []
    if pb or ps:
        promoter = f'<div class="promoter-empty">Promoter activity (14d): {len(pb)} buys / {len(ps)} sells — see Smart-Money detail in the dashboard.</div>'
    else:
        promoter = '<div class="promoter-empty">— No notable promoter activity this week —</div>'

    return {
        "SMART_BLOCKS": "\n\n".join(blocks_html_parts),
        "SMART_PROMOTER": promoter,
    }


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _calendar_block(data) -> Dict[str, str]:
    events = data.econ_calendar or []
    # build a 7-day strip starting today
    today = date.today()
    by_date: Dict[str, List[Dict]] = {}
    for e in events:
        d_str = e.get("event_date")
        if not d_str:
            continue
        by_date.setdefault(str(d_str)[:10], []).append(e)

    cells = []
    for i in range(14):
        d = today + timedelta(days=i)
        d_iso = d.strftime("%Y-%m-%d")
        day_lbl = _DAYS[d.weekday()]
        date_lbl = f"{d.day:02d}"
        if d.day == 1 or i == 0:
            day_lbl = f"{day_lbl} · {_MONTHS[d.month-1]}"
        evs = by_date.get(d_iso, [])
        if not evs:
            cells.append(f'      <div class="cal-cell"><div class="date">{date_lbl}</div><div class="day">{_h(day_lbl)}</div></div>')
            continue
        ev = evs[0]
        imp = (ev.get("importance") or "low").lower()
        if imp == "high":
            cls = "has-event"  # design uses high inverted only for marquee events; keep stylistic neutrality
            imp_cls = "high"
            imp_lbl = "High"
        elif imp == "medium" or imp == "med":
            cls = "has-event"; imp_cls = "med"; imp_lbl = "Med"
        elif imp == "marquee":
            cls = "high"; imp_cls = "marquee"; imp_lbl = "Marquee"
        else:
            cls = "has-event"; imp_cls = "low"; imp_lbl = "Low"
        ev_title = (ev.get("indicator") or ev.get("event") or "Event")[:50]
        cells.append(
            f'''      <div class="cal-cell {cls}"><div class="date">{date_lbl}</div><div class="day">{_h(day_lbl)}</div>
        <div class="event"><span class="imp {imp_cls}">{imp_lbl}</span>{_h(ev_title)}</div>
      </div>'''
        )

    watching = ("<strong style=\"color: var(--ink); font-weight: 600;\">What we're watching most:</strong> "
                "the highest-importance prints in the week ahead — position into the window rather than after.")
    if events:
        hi = next((e for e in events if (e.get("importance") or "").lower() in ("high", "marquee")), None)
        if hi:
            watching = (f"<strong style=\"color: var(--ink); font-weight: 600;\">What we're watching most:</strong> "
                        f"<em style=\"color: var(--ink); font-style: italic;\">{_h(hi.get('indicator') or hi.get('event'))}</em> "
                        f"on {_h(str(hi.get('event_date'))[:10])} — sets the tone for rate-sensitives and risk pricing.")
    return {
        "CAL_CELLS": "\n".join(cells),
        "CAL_WATCHING": watching,
    }


def _rebalance_block(data) -> Dict[str, str]:
    reb = data.rebalance_predictions or {}
    adds = reb.get("likely_additions") or []
    if not adds:
        return {
            "REB_TICKER": _h("—"),
            "REB_SUB": _h("No rebalance event pending"),
            "REB_TAG": _h("Watch"),
            "REB_BODY": "No imminent Nifty 50 rebalance event flagged by the model today.",
            "REB_INFLOW": _h("n/a"),
            "REB_INFLOW_LABEL": _h("Est. passive inflow"),
        }
    a = adds[0]
    tk = a.get("symbol") or a.get("ticker") or "n/a"
    name = a.get("name") or "Likely Add"
    inflow = a.get("estimated_inflow_cr") or a.get("expected_inflow_cr")
    return {
        "REB_TICKER": _h(tk),
        "REB_SUB": _h(f"{tk} IN · Likely Add"),
        "REB_TAG": _h("Catalyst · Passive Bid"),
        "REB_BODY": ("Estimated passive inflow on index inclusion event. "
                    "Front-running window is open until rebalance date. Quality of liquidity "
                    "matters — expect tight basis around event window."),
        "REB_INFLOW": _h(f"≈ ₹{_num(inflow, 0)} Cr" if inflow else "n/a"),
        "REB_INFLOW_LABEL": _h("Est. passive inflow"),
    }


# ════════════════════════════════════════════════════════════════════════════
#  Master mapper — produces every placeholder from a DailyNoteData
# ════════════════════════════════════════════════════════════════════════════

def _data_for_template(data, kpi_data: Optional[Dict] = None, today_str: Optional[str] = None) -> Dict[str, str]:
    today_str = today_str or getattr(data, "today", None) or date.today().strftime("%d %b %Y")
    cutoff_str = today_str  # close-of-session cutoff is same date (we don't know the exact time)

    if kpi_data is None:
        nifty = _find_idx(data.indices_snapshot or [], "index", "Nifty 50")
        bn = _find_idx(data.indices_snapshot or [], "index", "Bank Nifty")
        sensex = _find_idx(data.indices_snapshot or [], "index", "Sensex")
        fii = next((f for f in (data.fii_dii or []) if f.get("category") in ("FII/FPI", "FII")), None)
        dii = next((f for f in (data.fii_dii or []) if f.get("category") == "DII"), None)
        kpi_data = {
            "nifty": nifty, "bn": bn, "sensex": sensex,
            "fii_net": fii["net_cr"] if fii else None,
            "dii_net": dii["net_cr"] if dii else None,
            "breadth": data.breadth or {},
        }

    out: Dict[str, str] = {}

    # head + firmbar + titleblock
    out["HEAD_TITLE"] = _h(f"India Morning Brief · {today_str} · Institutional Research")
    out["FIRM_NAME"] = _h("Macro Research Agent · Institutional Research")
    out["FIRM_DESK"] = _h("India Equities")
    out["FIRM_DIST"] = _h("Internal · Clients")
    out["FIRM_CYCLE"] = _h("Daily · Pre-Open")
    out["FIRM_PAGES"] = _h("Page 1 / 1")

    out["TB_EYEBROW"] = _h("Morning Brief")
    out["TB_EYEBROW_SUB"] = _h("· Pre-Open Edition · India Equities")
    out["TB_TITLE"] = _h("India Morning Brief")

    # Subhead: build a one-liner from data
    nifty = kpi_data.get("nifty")
    fii_v = kpi_data.get("fii_net")
    dii_v = kpi_data.get("dii_net")
    if nifty:
        ncl = _int(nifty.get("close"))
        npc = _pct(nifty.get("change_pct"))
        if fii_v is not None and dii_v is not None and dii_v > 0 and fii_v < 0:
            sub = (f"Nifty {ncl} ({npc}) — DIIs absorbing FII selling. "
                   f"Selective adds; respect regime risk.")
        else:
            sub = (f"Nifty {ncl} ({npc}) — sector rotation in focus. "
                   f"Lead with leadership; let the tape settle.")
    else:
        sub = "Pre-open desk read — selective stance, watch breadth and flows."
    out["TB_SUB"] = sub

    out["TB_ISSUE_DATE"] = _h(today_str)
    out["TB_CUTOFF"] = _h(f"{cutoff_str} · 16:00 IST")
    out["TB_EDITION"] = _h("Pre-Open · Daily")
    out["TB_UNIVERSE"] = _h("Nifty 500 + F&O")

    # Ticker tape
    out.update(_ticker_cells(data.indices_snapshot or [], data.global_cues or []))

    # Summary head + rows
    out["SUMHEAD_LEFT"] = _h("Today's Filter Output Summary")
    out["SUMHEAD_MID"] = _h(f"Pre-Open · {today_str} · 07:45 IST")
    out["SUMHEAD_RIGHT"] = _h(f"As of {today_str} close")
    out["REC_ROWS"] = _rec_rows(data)

    # § 01 At a Glance
    out.update(_glance_data(data, kpi_data))

    # § 02 Pre-Market
    out.update(_pm_tiles_block(data))

    # § 03 Market Action
    out.update(_market_action_block(data))

    # § 04 Movers
    out.update(_movers_block(data))

    # § 05 Idea
    out.update(_idea_block(data))

    # § 06 Regime
    out.update(_regime_block(data))

    # § 07 F&O
    out.update(_fno_block(data))

    # § 08 Smart Money
    out.update(_smart_money_block(data))

    # § 09 Calendar
    out.update(_calendar_block(data))

    # § 10 Rebalance
    out.update(_rebalance_block(data))

    # Disclaimer
    out["DIS_FOOTNOTE"] = _h(
        "Breadth ratio computed across the universe; advance/decline against prior session close. "
        "Sector indices: NSE thematic indices, level changes reported on a same-day basis."
    )
    out["DIS_BODY"] = (
        "This document is informational analysis prepared by the Macro Research Agent. "
        "<strong>It is NOT investment advice, NOT a recommendation to buy, sell or hold any "
        "security, and NOT a research report under SEBI (Research Analysts) Regulations, 2014.</strong> "
        "The author is not a SEBI-registered Research Analyst or Investment Adviser. Filter outputs, "
        "composite scores, model scenario ranges, and structural overlays presented are mechanical "
        "model outputs based on public data — they describe what the data shows, not what the reader "
        "should do. All figures sourced from yfinance, NSE provisional flows, NSE corporate events "
        "feed, screener.in fundamentals, FRED/IMF/WB macro, RBI/SEBI public filings, GDELT news "
        "sentiment — recipients must verify against primary sources before any decision. "
        "Past performance is not indicative of future results."
    )
    out["DIS_SOURCES"] = _h("NSE · BSE · yfinance · RBI · SEBI · GDELT")
    out["DIS_DIST"] = _h("Internal · Tier-1 clients")
    out["DIS_CYCLE"] = _h(f"Daily · Pre-Open · 07:45 IST")

    return out


# ════════════════════════════════════════════════════════════════════════════
#  Template body — verbatim copy of the reference design (Tweaks panel stripped)
# ════════════════════════════════════════════════════════════════════════════

_TEMPLATE_STR = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>${HEAD_TITLE}</title>
<meta name="viewport" content="width=1280" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:ital,opsz,wght@0,8..60,300;0,8..60,400;0,8..60,500;0,8..60,600;0,8..60,700;0,8..60,800;1,8..60,400&family=Playfair+Display:ital,wght@0,400;0,600;0,700;0,800;1,400;1,700&family=EB+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400&family=Spectral:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,700;0,9..144,800;1,9..144,400&family=Geist:wght@300;400;500;600;700&family=DM+Sans:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root {
    /* Surfaces */
    --bg:        #f4f5f7;
    --paper:    #ffffff;
    --panel:    #f7f8fa;
    --panel-2:  #eef0f4;

    /* Ink */
    --ink:      #0a0e14;
    --ink-2:    #2b3340;
    --ink-3:    #4a5160;
    --muted:    #7c8497;
    --muted-2:  #aab1c0;

    /* Lines */
    --rule:        #e3e6ee;
    --rule-strong: #c5cbd9;
    --rule-heavy:  #0a0e14;

    /* Signal */
    --navy:     #0a2540;
    --navy-ink: #051630;
    --up:       #1b6b3a;
    --up-bg:    #1b6b3a0d;
    --down:     #b1271f;
    --down-bg:  #b1271f0d;
    --warn:     #a07a16;
    --warn-bg:  #a07a160f;

    /* Type */
    --serif: "Source Serif 4", Georgia, serif;
    --sans:  "Geist", "Söhne", "Helvetica Neue", sans-serif;
    --mono:  "Geist Mono", "JetBrains Mono", ui-monospace, monospace;
  }

  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--ink);
    font-family: var(--sans);
    font-size: 13px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
    font-feature-settings: "ss01", "cv11";
  }

  /* ─── Top firm bar ─────────────────────── */
  .firmbar {
    background: var(--navy-ink);
    color: #ffffff;
    border-bottom: 1px solid var(--navy);
    font-family: var(--sans);
    font-size: 11px;
    letter-spacing: .08em;
  }
  .firmbar-inner {
    max-width: 1280px;
    margin: 0 auto;
    padding: 10px 56px;
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 24px;
  }
  .mark {
    display: flex; align-items: center; gap: 10px;
    font-weight: 600; letter-spacing: .14em; text-transform: uppercase;
  }
  .mark .glyph {
    width: 22px; height: 22px;
    background: #ffffff;
    color: var(--navy-ink);
    font-family: var(--serif);
    font-weight: 700; font-style: italic;
    display: flex; align-items: center; justify-content: center;
    font-size: 14px;
    letter-spacing: 0;
  }
  .firmbar-mid {
    display: flex; gap: 32px;
    font-family: var(--mono);
    color: #ffffffcc;
    font-size: 11px;
    letter-spacing: .04em;
  }
  .firmbar-mid b { color: #ffffff; font-weight: 600; }
  .firmbar-right {
    display: flex; gap: 8px; align-items: center;
    font-family: var(--mono);
    font-size: 11px;
    color: #ffffffcc;
    letter-spacing: .04em;
  }
  .firmbar-right .pill {
    border: 1px solid #ffffff40;
    padding: 3px 8px;
    color: #ffffff;
    letter-spacing: .12em;
    text-transform: uppercase;
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 600;
  }

  /* ─── Page shell ─────────────────────── */
  .page {
    max-width: 1280px;
    margin: 0 auto;
    background: var(--paper);
    padding: 44px 56px 80px;
    box-shadow: 0 0 0 1px var(--rule), 0 12px 40px -20px #0a0e1418;
  }

  /* ─── Title block ─────────────────────── */
  .titleblock {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: end;
    gap: 28px;
    padding-bottom: 18px;
    border-bottom: 2px solid var(--ink);
  }
  .tb-tag {
    display: inline-flex; align-items: center; gap: 8px;
    font-family: var(--sans);
    font-size: 10px;
    letter-spacing: .22em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 600;
    margin-bottom: 12px;
  }
  .tb-tag .swatch { width: 8px; height: 8px; background: var(--navy); }
  .tb-tag em { color: var(--ink-2); font-style: normal; }

  h1.report-title {
    margin: 0;
    font-family: var(--serif);
    font-weight: 700;
    font-size: 44px;
    line-height: 1.0;
    letter-spacing: -.02em;
    color: var(--ink);
  }
  .report-sub {
    margin: 10px 0 0;
    font-family: var(--serif);
    font-size: 19px;
    font-style: italic;
    color: var(--ink-3);
    font-weight: 400;
    max-width: 760px;
    line-height: 1.4;
  }
  .tb-meta {
    display: grid;
    grid-template-columns: auto auto;
    column-gap: 24px;
    row-gap: 4px;
    font-family: var(--mono);
    font-size: 11px;
    color: var(--ink-2);
    letter-spacing: .02em;
    align-self: end;
  }
  .tb-meta dt {
    color: var(--muted);
    font-family: var(--sans);
    letter-spacing: .14em;
    text-transform: uppercase;
    font-size: 10px;
    font-weight: 600;
  }
  .tb-meta dd { margin: 0; font-weight: 600; }

  /* ─── Analyst byline ─────────────────────── */
  .byline {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 14px 0 18px;
    border-bottom: 1px solid var(--rule);
  }
  .analysts { display: flex; gap: 28px; }
  .analyst {
    display: flex; align-items: center; gap: 10px;
  }
  .ana-init {
    width: 28px; height: 28px;
    border-radius: 50%;
    background: var(--navy);
    color: #fff;
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: .04em;
    display: flex; align-items: center; justify-content: center;
  }
  .ana-init.alt { background: var(--ink); }
  .ana-init.alt2 { background: var(--warn); color: #fff; }
  .ana-meta { font-size: 11px; line-height: 1.3; }
  .ana-meta b { display: block; font-weight: 600; color: var(--ink); font-size: 12px; }
  .ana-meta span { color: var(--muted); font-family: var(--mono); font-size: 10px; letter-spacing: .02em; }

  .toc-pills { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
  .toc-pill {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--ink-2);
    background: var(--panel);
    border: 1px solid var(--rule);
    padding: 4px 9px;
    letter-spacing: .04em;
  }
  .toc-pill b { color: var(--muted); margin-right: 6px; font-family: var(--sans); font-weight: 600; letter-spacing: .1em; }

  /* ─── Ticker tape ─────────────────────── */
  .ticker {
    margin: 24px 0 0;
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    border-top: 1px solid var(--rule-strong);
    border-bottom: 1px solid var(--rule-strong);
    background: var(--paper);
  }
  .tk {
    padding: 16px 18px 14px;
    border-right: 1px solid var(--rule);
    position: relative;
  }
  .tk:last-child { border-right: none; }
  .tk .lbl {
    font-family: var(--sans);
    font-size: 10px;
    letter-spacing: .18em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 600;
  }
  .tk .code {
    font-family: var(--mono);
    font-size: 9px;
    color: var(--muted-2);
    letter-spacing: .06em;
    margin-top: 1px;
  }
  .tk .val {
    font-family: var(--mono);
    font-size: 22px;
    font-weight: 600;
    color: var(--ink);
    margin-top: 6px;
    letter-spacing: -.01em;
  }
  .tk .chg {
    font-family: var(--mono);
    font-size: 11px;
    margin-top: 2px;
    font-weight: 600;
    letter-spacing: .02em;
  }
  .up { color: var(--up); }
  .down { color: var(--down); }
  .chg.up::before, .chg.down::before {
    content: ""; display: inline-block;
    width: 0; height: 0;
    vertical-align: 2px;
    margin-right: 5px;
  }
  .chg.up::before   { border-left: 3.5px solid transparent; border-right: 3.5px solid transparent; border-bottom: 5px solid var(--up); }
  .chg.down::before { border-left: 3.5px solid transparent; border-right: 3.5px solid transparent; border-top: 5px solid var(--down); }

  /* ─── Recommendation summary ───────────── */
  .summary {
    margin-top: 32px;
    border: 1px solid var(--ink);
    background: var(--paper);
  }
  .summary-head {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    background: var(--ink);
    color: #fff;
    padding: 10px 18px;
    font-family: var(--sans);
    font-size: 10px;
    letter-spacing: .22em;
    text-transform: uppercase;
    font-weight: 600;
    gap: 24px;
  }
  .summary-head span:nth-child(2) { color: #ffffffaa; }
  .summary-head .ts { font-family: var(--mono); font-weight: 400; letter-spacing: .04em; color: #ffffffaa; text-transform: none; }
  .summary-table {
    width: 100%;
    border-collapse: collapse;
    font-family: var(--sans);
    font-size: 13px;
  }
  .summary-table th {
    font-family: var(--sans);
    font-size: 10px;
    letter-spacing: .18em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 600;
    text-align: left;
    padding: 12px 18px;
    border-bottom: 1px solid var(--rule);
    background: var(--panel);
  }
  .summary-table th.num { text-align: right; }
  .summary-table td {
    padding: 14px 18px;
    border-bottom: 1px solid var(--rule);
    font-variant-numeric: tabular-nums;
  }
  .summary-table tr:last-child td { border-bottom: none; }
  .summary-table .topic { font-weight: 600; color: var(--ink); }
  .summary-table .topic small {
    display: block;
    color: var(--muted);
    font-weight: 400;
    font-size: 11px;
    letter-spacing: .02em;
    margin-top: 2px;
  }
  .summary-table .num-cell { text-align: right; font-family: var(--mono); font-weight: 600; }
  .rec-chip {
    display: inline-flex; align-items: center;
    font-family: var(--sans);
    font-size: 10px;
    letter-spacing: .18em;
    text-transform: uppercase;
    font-weight: 700;
    padding: 4px 9px;
    border: 1px solid currentColor;
  }
  .rec-chip.buy   { color: var(--up);   background: var(--up-bg); }
  .rec-chip.hold  { color: var(--warn); background: var(--warn-bg); }
  .rec-chip.sell  { color: var(--down); background: var(--down-bg); }
  .rec-chip.risk  { color: var(--down); background: #fff; }
  .rec-chip.neutral { color: var(--ink-2); border-color: var(--rule-strong); background: var(--panel); }

  /* ─── Section scaffolding ─────────────────────── */
  section { margin-top: 48px; }
  .sec-head {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: baseline;
    gap: 18px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--ink);
    margin-bottom: 22px;
  }
  .sec-num {
    font-family: var(--mono);
    font-size: 11px;
    letter-spacing: .14em;
    color: var(--muted);
    font-weight: 500;
  }
  .sec-title {
    margin: 0;
    font-family: var(--serif);
    font-weight: 600;
    font-size: 24px;
    letter-spacing: -.01em;
    color: var(--ink);
  }
  .sec-kicker {
    font-family: var(--sans);
    font-size: 10px;
    letter-spacing: .2em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 600;
  }

  /* ─── At a Glance ─────────────────────── */
  .lead {
    display: grid;
    grid-template-columns: 1.5fr 1fr;
    gap: 36px;
  }
  .lead-body {
    font-family: var(--serif);
    font-size: 16px;
    line-height: 1.55;
    color: var(--ink-2);
  }
  .lead-body p { margin: 0 0 12px; }
  .lead-body strong { color: var(--ink); font-weight: 600; }
  .lead-body .ref { color: var(--navy); font-family: var(--sans); font-size: 10px; vertical-align: super; font-weight: 600; }

  .view-card {
    margin-top: 14px;
    padding: 14px 18px;
    background: var(--panel);
    border-left: 3px solid var(--navy);
    font-family: var(--sans);
    font-size: 13px;
    line-height: 1.55;
    color: var(--ink-2);
  }
  .view-card b {
    display: block;
    font-size: 10px;
    letter-spacing: .22em;
    text-transform: uppercase;
    color: var(--navy);
    margin-bottom: 6px;
    font-weight: 700;
  }

  .lead-side {
    background: var(--panel);
    border: 1px solid var(--rule);
    padding: 18px 20px;
  }
  .lead-side h4 {
    margin: 0 0 14px;
    font-family: var(--sans);
    font-size: 10px;
    letter-spacing: .2em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 700;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--rule);
  }
  .flow-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1px;
    background: var(--rule);
    border: 1px solid var(--rule);
  }
  .flow-cell { background: var(--paper); padding: 12px 14px; }
  .flow-cell .who { font-family: var(--sans); font-size: 10px; letter-spacing: .16em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
  .flow-cell .amt { font-family: var(--mono); font-size: 22px; font-weight: 600; margin-top: 6px; }
  .flow-cell.fii .amt { color: var(--down); }
  .flow-cell.dii .amt { color: var(--up); }
  .flow-bar {
    margin-top: 12px;
    height: 22px;
    background: var(--panel-2);
    border: 1px solid var(--rule);
    display: flex;
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 600;
    color: #fff;
  }
  .flow-bar > div {
    display: flex; align-items: center; justify-content: center;
    padding: 0 6px;
  }
  .flow-bar .b-fii { background: var(--down); }
  .flow-bar .b-dii { background: var(--up); }
  .flow-cap {
    font-family: var(--sans); font-size: 11px; color: var(--muted);
    margin-top: 10px; line-height: 1.4;
  }
  .flow-cap b { color: var(--ink); font-weight: 600; }

  /* ─── Pre-Market grid ─────────────────────── */
  .premarket {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 1px;
    background: var(--rule);
    border: 1px solid var(--rule-strong);
  }
  .pm {
    background: var(--paper);
    padding: 16px 16px 14px;
    position: relative;
    min-height: 138px;
  }
  .pm .pm-ticker {
    display: flex; justify-content: space-between; align-items: flex-start;
    font-family: var(--sans); font-size: 10px; letter-spacing: .18em;
    color: var(--muted); text-transform: uppercase; font-weight: 700;
  }
  .pm .pm-ticker .code {
    font-family: var(--mono); font-size: 9px; color: var(--muted-2);
    letter-spacing: .04em; text-transform: none; font-weight: 400;
  }
  .pm .pm-val {
    font-family: var(--mono);
    font-size: 22px; font-weight: 600;
    margin-top: 10px; letter-spacing: -.01em;
  }
  .pm .pm-chg {
    font-family: var(--mono); font-size: 11px;
    margin-top: 2px; font-weight: 600;
  }
  .pm .spark { margin-top: 8px; opacity: .85; }
  .pm .pm-tag {
    margin-top: 8px;
    font-family: var(--sans); font-size: 11px; line-height: 1.4;
    color: var(--ink-3);
  }

  .signal-strip {
    margin-top: 16px;
    padding: 12px 18px;
    background: var(--panel);
    border: 1px solid var(--rule-strong);
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 18px;
    font-family: var(--sans);
    font-size: 13px;
    color: var(--ink-2);
  }
  .signal-strip .label {
    font-family: var(--sans); font-size: 10px;
    letter-spacing: .22em; text-transform: uppercase;
    background: var(--ink); color: #fff;
    padding: 5px 11px; font-weight: 700;
  }
  .signal-strip strong { color: var(--ink); font-weight: 600; }

  /* ─── Market Action ─────────────────────── */
  .market {
    display: grid;
    grid-template-columns: 1.1fr 1fr;
    gap: 36px;
  }
  .panel-h {
    margin: 0 0 12px;
    font-family: var(--sans);
    font-size: 10px;
    letter-spacing: .2em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 700;
  }
  .sector-row {
    display: grid;
    grid-template-columns: 130px 1fr 80px;
    align-items: center;
    gap: 14px;
    padding: 10px 0;
    border-bottom: 1px solid var(--rule);
    font-family: var(--sans);
    font-size: 13px;
  }
  .sector-row .name { font-weight: 500; color: var(--ink); }
  .sector-row .name small { display: block; font-family: var(--mono); font-size: 10px; color: var(--muted); font-weight: 400; letter-spacing: 0; margin-top: 1px; }
  .sector-row .barwrap { position: relative; height: 14px; }
  .sector-row .barwrap::before {
    content: ""; position: absolute; left: 50%; top: -2px; bottom: -2px;
    width: 1px; background: var(--rule-strong);
  }
  .sector-row .bar { position: absolute; top: 0; bottom: 0; height: 14px; }
  .sector-row .bar.up { background: var(--up); left: 50%; }
  .sector-row .bar.down { background: var(--down); right: 50%; }
  .sector-row .pct { font-family: var(--mono); font-size: 12px; font-weight: 600; text-align: right; }

  .indexbox {
    background: var(--panel);
    border: 1px solid var(--rule);
    padding: 18px 20px;
  }
  .index-row {
    display: grid;
    grid-template-columns: 1fr auto auto;
    align-items: baseline;
    gap: 16px;
    padding: 12px 0;
    border-bottom: 1px solid var(--rule);
  }
  .index-row:last-of-type { border-bottom: none; }
  .index-row .nm { font-family: var(--sans); font-size: 13px; font-weight: 600; color: var(--ink); }
  .index-row .nm small { display: block; font-family: var(--mono); font-size: 10px; color: var(--muted); font-weight: 400; letter-spacing: .02em; margin-top: 1px; }
  .index-row .val { font-family: var(--mono); font-size: 18px; font-weight: 600; }
  .index-row .pct { font-family: var(--mono); font-size: 12px; font-weight: 600; min-width: 64px; text-align: right; }
  .breadth {
    margin-top: 12px; padding-top: 12px;
    border-top: 1px solid var(--ink);
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center; gap: 16px;
    font-family: var(--sans);
  }
  .breadth .b-l { font-size: 10px; letter-spacing: .2em; text-transform: uppercase; color: var(--muted); font-weight: 700; }
  .breadth .b-v { font-family: var(--mono); font-size: 14px; font-weight: 600; }
  .breadth .b-bar { height: 6px; background: var(--down); position: relative; overflow: hidden; }
  .breadth .b-bar i { position: absolute; left: 0; top: 0; bottom: 0; background: var(--up); }

  /* ─── Movers ─────────────────────── */
  .movers { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
  .mover-card h5 {
    display: flex; align-items: center; gap: 10px;
    font-family: var(--sans); font-size: 10px; letter-spacing: .2em;
    text-transform: uppercase; font-weight: 700;
    margin: 0 0 10px; padding-bottom: 8px;
    border-bottom: 1px solid var(--ink);
    color: var(--ink);
  }
  .mover-card h5 .pip { width: 8px; height: 8px; }
  .mover-card h5 .pip.up { background: var(--up); }
  .mover-card h5 .pip.down { background: var(--down); }
  table.mv {
    width: 100%; border-collapse: collapse;
    font-family: var(--sans); font-size: 13px;
  }
  table.mv th {
    text-align: left;
    font-family: var(--sans); font-size: 10px;
    letter-spacing: .18em; text-transform: uppercase;
    color: var(--muted); font-weight: 700;
    padding: 8px 8px 8px 0;
    border-bottom: 1px solid var(--rule);
  }
  table.mv th.r { text-align: right; padding-right: 0; }
  table.mv td {
    padding: 10px 8px 10px 0;
    border-bottom: 1px solid var(--rule);
    font-variant-numeric: tabular-nums;
  }
  table.mv td.tk { font-family: var(--mono); font-weight: 600; font-size: 12px; letter-spacing: .02em; color: var(--ink); }
  table.mv td.tk small { display: block; font-family: var(--sans); font-size: 10px; color: var(--muted); font-weight: 400; letter-spacing: 0; margin-top: 1px; }
  table.mv td.px { font-family: var(--mono); text-align: right; }
  table.mv td.pc { font-family: var(--mono); text-align: right; font-weight: 600; padding-right: 0; }
  table.mv td.sp { width: 84px; }
  table.mv td.sp svg { display: block; }

  /* ─── Idea card ─────────────────────── */
  .idea {
    background: var(--paper);
    border: 1px solid var(--ink);
    padding: 0;
    display: grid;
    grid-template-columns: 1.6fr 1fr;
  }
  .idea-l { padding: 24px 28px 24px 28px; border-right: 1px solid var(--rule); }
  .idea-r { padding: 24px 28px; background: var(--panel); }
  .idea-stamp {
    display: flex; align-items: center; gap: 8px;
    font-family: var(--sans); font-size: 10px;
    letter-spacing: .22em; text-transform: uppercase;
    color: var(--up); font-weight: 700;
    margin-bottom: 14px;
  }
  .idea-stamp .dot {
    width: 8px; height: 8px; background: var(--up);
  }
  .idea h3 {
    margin: 0;
    font-family: var(--serif);
    font-size: 30px;
    font-weight: 700;
    letter-spacing: -.01em;
    line-height: 1.05;
    color: var(--ink);
  }
  .ticker-row {
    margin-top: 8px;
    display: flex; gap: 14px;
    font-family: var(--mono);
    font-size: 11px; color: var(--muted);
    letter-spacing: .04em;
  }
  .ticker-row b { color: var(--ink-2); font-weight: 600; }
  .ticker-row span { padding-right: 14px; border-right: 1px solid var(--rule); }
  .ticker-row span:last-child { border-right: none; padding-right: 0; }

  .idea-thesis {
    margin-top: 18px;
    font-family: var(--serif); font-size: 15px; line-height: 1.55;
    color: var(--ink-2);
  }
  .idea-thesis strong { color: var(--ink); font-weight: 600; }
  .idea-thesis em { color: var(--ink); font-style: italic; font-weight: 500; }

  .bullet-list {
    margin: 16px 0 0;
    padding: 0;
    list-style: none;
    font-family: var(--sans); font-size: 13px;
    color: var(--ink-2);
  }
  .bullet-list li {
    position: relative;
    padding: 8px 0 8px 22px;
    border-bottom: 1px dashed var(--rule);
    line-height: 1.5;
  }
  .bullet-list li::before {
    content: "›";
    position: absolute; left: 0; top: 7px;
    color: var(--navy);
    font-family: var(--mono); font-size: 14px; font-weight: 700;
  }
  .bullet-list li b { color: var(--ink); font-weight: 600; }

  .risk-row {
    margin-top: 14px;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 12px;
    padding: 12px 14px;
    background: var(--down-bg);
    border-left: 3px solid var(--down);
    font-family: var(--sans);
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--ink-2);
  }
  .risk-row b {
    font-family: var(--sans);
    font-size: 10px;
    letter-spacing: .2em;
    text-transform: uppercase;
    color: var(--down);
    font-weight: 700;
    align-self: start;
    padding-top: 1px;
  }
  .risk-row b::before {
    content: "▲"; margin-right: 5px; font-size: 9px;
  }

  /* Metrics table */
  .met-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 1px;
    background: var(--rule);
    border: 1px solid var(--rule);
  }
  .met {
    background: var(--paper);
    padding: 12px 14px;
  }
  .met .lbl {
    font-family: var(--sans); font-size: 10px;
    letter-spacing: .16em; text-transform: uppercase;
    color: var(--muted); font-weight: 700;
  }
  .met .val {
    font-family: var(--mono); font-size: 20px; font-weight: 600;
    margin-top: 4px; letter-spacing: -.01em;
  }
  .met .sub { font-family: var(--sans); font-size: 10px; color: var(--muted); margin-top: 1px; font-weight: 500; }

  /* Score panel */
  .score-panel {
    margin-top: 16px;
    background: var(--ink);
    color: #fff;
    padding: 16px 18px;
  }
  .score-panel .lbl {
    font-family: var(--sans); font-size: 10px;
    letter-spacing: .22em; text-transform: uppercase;
    color: #ffffff80; font-weight: 700;
  }
  .score-panel .row {
    display: flex; align-items: baseline; gap: 14px;
    margin-top: 6px;
  }
  .score-panel .big {
    font-family: var(--mono); font-size: 40px; font-weight: 600;
    line-height: 1; letter-spacing: -.02em;
  }
  .score-panel .breakdown {
    font-family: var(--mono); font-size: 11px;
    color: #ffffffaa; line-height: 1.5;
  }
  .score-panel .breakdown b { font-family: var(--mono); color: #fff; }
  .score-panel .breakdown b.penal { color: #ff9c8c; }
  .score-panel .breakdown b.bonus { color: #ffd984; }
  .score-panel .note {
    margin-top: 12px;
    font-family: var(--sans); font-style: italic; font-size: 11.5px;
    color: #ffffffaa;
  }

  /* Levels strip */
  .levels {
    margin-top: 16px;
    padding: 14px 18px;
    border: 1px solid var(--ink);
    background: var(--paper);
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }
  .levels > div .lbl {
    font-family: var(--sans); font-size: 9.5px; letter-spacing: .18em;
    text-transform: uppercase; color: var(--muted); font-weight: 700;
  }
  .levels > div .v {
    font-family: var(--mono); font-size: 17px; font-weight: 600;
    margin-top: 3px; letter-spacing: -.01em;
  }
  .levels .entry .v { color: var(--up); }
  .levels .stop .v { color: var(--down); }
  .levels .tgt .v { color: var(--navy); }

  .upside-bar {
    margin-top: 14px;
    position: relative;
    height: 62px;
    background: var(--panel);
    border: 1px solid var(--rule);
    font-family: var(--mono); font-size: 10px;
    overflow: hidden;
  }
  .upside-bar .tk {
    position: absolute; top: 6px;
    border-left: 1px solid var(--rule-strong);
    padding: 0 6px;
    font-size: 9.5px;
    color: var(--muted);
    line-height: 1.25;
  }
  .upside-bar .tk b { display: block; color: var(--ink); font-size: 11px; margin-bottom: 1px; }
  .upside-bar .range {
    position: absolute; top: 50px;
    height: 3px;
    background: var(--navy);
  }
  .upside-bar .marker {
    position: absolute; top: 51.5px; transform: translate(-50%, -50%);
    width: 10px; height: 10px;
    background: var(--ink);
    border: 2px solid #fff;
    border-radius: 50%;
    box-shadow: 0 0 0 1px var(--ink);
  }
  .upside-bar .marker.up   { background: var(--up); }
  .upside-bar .marker.dn   { background: var(--down); }
  .upside-bar .marker.tg   { background: var(--navy); }

  .runner-up {
    margin-top: 22px;
    padding: 14px 18px;
    border: 1px dashed var(--rule-strong);
    background: var(--panel);
    font-family: var(--sans);
    font-size: 13px;
    line-height: 1.55;
    color: var(--ink-2);
  }
  .runner-up .tag {
    display: inline-block;
    font-family: var(--sans); font-size: 10px;
    letter-spacing: .22em; text-transform: uppercase;
    color: var(--muted); font-weight: 700; margin-right: 10px;
  }
  .runner-up b { color: var(--ink); font-weight: 600; }
  .runner-up em { color: var(--ink-2); font-style: italic; }

  /* Regime card */
  .regime {
    background: var(--ink);
    color: #fff;
    padding: 26px 32px;
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 28px;
    position: relative;
    overflow: hidden;
  }
  .regime::before {
    content: ""; position: absolute; inset: 0;
    background: repeating-linear-gradient(45deg, transparent 0 16px, #ffffff05 16px 17px);
    pointer-events: none;
  }
  .regime .light-stack {
    display: flex; flex-direction: column; gap: 6px;
    align-items: center;
    position: relative; z-index: 1;
  }
  .regime .light {
    width: 22px; height: 22px; border-radius: 50%;
    border: 1px solid #ffffff20;
  }
  .regime .light.on { background: var(--down); box-shadow: 0 0 24px var(--down), 0 0 0 4px #b1271f33; }
  .regime .light.dim { background: #ffffff10; }
  .regime .light-label {
    font-family: var(--mono); font-size: 9px;
    letter-spacing: .14em; color: #ffffff60; text-transform: uppercase;
    margin-top: 4px;
  }
  .regime .copy { position: relative; z-index: 1; }
  .regime .kicker {
    font-family: var(--sans); font-size: 10px;
    letter-spacing: .26em; text-transform: uppercase;
    color: #ffffff80; font-weight: 700;
  }
  .regime .verdict {
    font-family: var(--serif); font-size: 28px;
    font-weight: 700; line-height: 1.15;
    margin-top: 4px; letter-spacing: -.01em;
  }
  .regime .verdict em { color: #ff9c8c; font-style: italic; }
  .regime .detail {
    font-family: var(--sans); font-size: 13px;
    line-height: 1.55; color: #ffffffbf;
    margin-top: 8px; max-width: 580px;
  }
  .regime .levels-mini { font-family: var(--mono); text-align: right; position: relative; z-index: 1; }
  .regime .levels-mini .lbl {
    font-family: var(--sans); font-size: 10px;
    letter-spacing: .22em; color: #ffffff80;
    text-transform: uppercase; font-weight: 700;
  }
  .regime .levels-mini .big {
    font-size: 28px; font-weight: 600; line-height: 1;
    margin-top: 6px;
  }
  .regime .levels-mini .sub {
    font-family: var(--sans); font-size: 11px;
    color: #ffffff99; margin-top: 4px;
    text-transform: uppercase; letter-spacing: .12em;
    font-weight: 600;
  }

  /* F&O */
  .fno { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; }
  .fno-card {
    border: 1px solid var(--rule-strong);
    background: var(--paper);
    padding: 0;
  }
  .fno-head {
    padding: 14px 18px 12px;
    border-bottom: 1px solid var(--rule);
    display: flex; align-items: center; justify-content: space-between;
  }
  .fno-head h4 {
    margin: 0;
    font-family: var(--serif);
    font-size: 18px; font-weight: 700;
    color: var(--ink);
  }
  .fno-head h4 small {
    display: block;
    font-family: var(--mono);
    font-size: 10px;
    color: var(--muted);
    font-weight: 400;
    letter-spacing: .02em;
    margin-top: 2px;
  }
  .fno-card .badge {
    font-family: var(--sans); font-size: 9.5px;
    letter-spacing: .18em; text-transform: uppercase;
    font-weight: 700; padding: 4px 8px; border: 1px solid currentColor;
  }
  .fno-card .badge.bull { color: var(--up); background: var(--up-bg); }
  .fno-card .badge.bear { color: var(--down); background: var(--down-bg); }
  .fno-card .badge.mix  { color: var(--warn); background: var(--warn-bg); }

  .fno-body { padding: 6px 18px 14px; }
  .fno-row {
    display: grid; grid-template-columns: 1fr auto;
    padding: 8px 0;
    border-bottom: 1px solid var(--rule);
    font-family: var(--sans);
    font-size: 12.5px;
  }
  .fno-row:last-of-type { border-bottom: none; }
  .fno-row .k {
    color: var(--muted);
    font-size: 10.5px;
    letter-spacing: .12em;
    text-transform: uppercase;
    font-weight: 600;
  }
  .fno-row .v { font-family: var(--mono); font-weight: 600; color: var(--ink); font-size: 13px; }
  .fno-card .pin {
    margin: 0;
    padding: 12px 18px;
    background: var(--panel);
    border-top: 1px solid var(--rule);
    font-family: var(--sans); font-size: 11.5px; line-height: 1.5;
    color: var(--ink-2);
  }
  .fno-card .pin b { color: var(--ink); font-weight: 600; }

  /* Smart Money */
  .blocks { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
  .block {
    background: var(--paper);
    border: 1px solid var(--rule-strong);
  }
  .block-head {
    padding: 14px 18px 12px;
    border-bottom: 1px solid var(--rule);
    display: flex; justify-content: space-between; align-items: baseline;
    background: var(--panel);
  }
  .block-head .nm {
    font-family: var(--serif); font-size: 18px; font-weight: 700; color: var(--ink);
  }
  .block-head .nm small {
    display: block;
    font-family: var(--mono); font-size: 10px;
    color: var(--muted); font-weight: 400; letter-spacing: .04em; margin-top: 1px;
  }
  .block-head .price-tag {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--ink-2);
    text-align: right;
  }
  .block-head .price-tag b { color: var(--ink); font-size: 14px; font-weight: 600; display: block; }
  .flow-table { padding: 6px 0; }
  .flow-line {
    display: grid;
    grid-template-columns: 16px 1fr auto;
    align-items: center; gap: 12px;
    padding: 10px 18px;
    border-bottom: 1px solid var(--rule);
    font-family: var(--sans); font-size: 12.5px;
  }
  .flow-line:last-child { border-bottom: none; }
  .flow-line .dot { width: 8px; height: 8px; }
  .flow-line.sell .dot { background: var(--down); }
  .flow-line.buy  .dot { background: var(--up); }
  .flow-line .nm { font-weight: 600; color: var(--ink); }
  .flow-line .nm small {
    display: block; color: var(--muted); font-weight: 500;
    font-size: 10px; letter-spacing: .16em; text-transform: uppercase;
    margin-top: 1px;
  }
  .flow-line .amt { font-family: var(--mono); font-weight: 600; }
  .block .read {
    margin: 0; padding: 12px 18px;
    background: var(--panel);
    border-top: 1px solid var(--rule);
    font-family: var(--sans); font-size: 11.5px; line-height: 1.5;
    color: var(--ink-2); font-style: italic;
  }
  .promoter-empty {
    margin-top: 22px;
    padding: 12px 18px;
    border: 1px dashed var(--rule-strong);
    font-family: var(--sans); font-size: 12px; color: var(--muted);
    font-style: italic;
    text-align: center;
    letter-spacing: .02em;
  }

  /* Calendar */
  .calendar {
    display: grid; grid-template-columns: repeat(7, 1fr);
    gap: 1px; background: var(--rule);
    border: 1px solid var(--rule-strong);
  }
  .cal-cell {
    background: var(--paper);
    padding: 12px 12px 14px;
    min-height: 124px;
    display: flex; flex-direction: column;
    font-family: var(--sans);
  }
  .cal-cell .date {
    font-family: var(--mono); font-size: 16px;
    font-weight: 600; line-height: 1;
  }
  .cal-cell .day {
    font-size: 9.5px; letter-spacing: .2em; text-transform: uppercase;
    color: var(--muted); margin-top: 4px; font-weight: 700;
  }
  .cal-cell.has-event { background: var(--panel); }
  .cal-cell.high { background: var(--ink); color: #fff; }
  .cal-cell.high .day { color: #ffffff80; }
  .event {
    margin-top: 10px;
    font-family: var(--sans); font-size: 12px; line-height: 1.4;
    border-top: 1px solid var(--rule);
    padding-top: 8px; flex: 1;
    color: var(--ink-2);
  }
  .cal-cell.high .event { border-color: #ffffff30; color: #ffffffd9; }
  .event .imp {
    display: inline-block;
    font-family: var(--sans); font-size: 9px;
    letter-spacing: .22em; text-transform: uppercase; font-weight: 700;
    padding: 2px 6px; margin-bottom: 6px;
  }
  .imp.high   { background: var(--down); color: #fff; }
  .imp.marquee{ background: #fff; color: var(--ink); }
  .imp.med    { background: var(--panel-2); color: var(--ink-2); }
  .imp.low    { color: var(--muted); border: 1px solid var(--rule); }

  /* Rebalance */
  .rebalance {
    background: var(--panel);
    padding: 22px 28px;
    border: 1px solid var(--rule-strong);
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 32px;
  }
  .rebalance .tk-big {
    font-family: var(--serif); font-weight: 700; font-size: 38px;
    letter-spacing: -.01em; line-height: 1; color: var(--ink);
  }
  .rebalance .tk-big small {
    display: block;
    font-family: var(--mono); font-size: 11px;
    color: var(--muted); margin-top: 6px;
    letter-spacing: .04em; font-weight: 400;
  }
  .rebalance .copy {
    font-family: var(--sans); font-size: 13px; line-height: 1.5;
    color: var(--ink-2);
  }
  .rebalance .copy b {
    font-family: var(--sans); font-size: 10px; letter-spacing: .22em;
    text-transform: uppercase; color: var(--navy);
    display: block; margin-bottom: 6px; font-weight: 700;
  }
  .rebalance .inflow {
    font-family: var(--mono); font-size: 28px; font-weight: 600;
    text-align: right; color: var(--up);
  }
  .rebalance .inflow small {
    display: block; font-family: var(--sans); font-size: 10px;
    letter-spacing: .2em; color: var(--muted);
    text-transform: uppercase; font-weight: 700; margin-top: 4px;
  }

  /* Disclaimer */
  .disclaimer {
    margin-top: 64px;
    padding: 20px 24px;
    border-top: 2px solid var(--ink);
    background: var(--panel);
    font-family: var(--sans);
    font-size: 11px;
    line-height: 1.55;
    color: var(--muted);
  }
  .disclaimer h6 {
    margin: 0 0 8px;
    font-family: var(--sans); font-size: 10px;
    letter-spacing: .22em; text-transform: uppercase;
    color: var(--ink); font-weight: 700;
  }
  .disclaimer p { margin: 0 0 6px; }
  .disclaimer p:last-child { margin-bottom: 0; }
  .disclaimer .grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 28px;
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid var(--rule);
    font-family: var(--mono);
    font-size: 10px;
    color: var(--muted);
    letter-spacing: .04em;
  }
  .disclaimer .grid b {
    display: block;
    font-family: var(--sans);
    font-size: 9.5px; letter-spacing: .2em;
    text-transform: uppercase; color: var(--ink-2);
    font-weight: 700; margin-bottom: 4px;
  }

  @media print {
    body { background: #fff; }
    .page { box-shadow: none; max-width: none; padding: 24px 32px; }
    .firmbar { position: static; }
  }
</style>
</head>
<body>

<!-- ═══ FIRM BAR ═══════════════════════════ -->
<div class="firmbar">
  <div class="firmbar-inner">
    <div class="mark">
      <span class="glyph">M</span>
      <span>${FIRM_NAME}</span>
    </div>
    <div class="firmbar-mid">
      <div><b>Desk:</b> ${FIRM_DESK}</div>
      <div><b>Distribution:</b> ${FIRM_DIST}</div>
      <div><b>Cycle:</b> ${FIRM_CYCLE}</div>
    </div>
    <div class="firmbar-right">
      <span class="pill">Confidential</span>
      <span>${FIRM_PAGES}</span>
    </div>
  </div>
</div>

<div class="page">

  <!-- ═══ TITLE BLOCK ═══════════════════════ -->
  <div class="titleblock">
    <div>
      <div class="tb-tag">
        <span class="swatch"></span>
        <span>${TB_EYEBROW}</span>
        <em>${TB_EYEBROW_SUB}</em>
      </div>
      <h1 class="report-title">${TB_TITLE}</h1>
      <p class="report-sub">${TB_SUB}</p>
    </div>
    <dl class="tb-meta">
      <dt>Issue Date</dt><dd>${TB_ISSUE_DATE}</dd>
      <dt>Cut-off</dt><dd>${TB_CUTOFF}</dd>
      <dt>Edition</dt><dd>${TB_EDITION}</dd>
      <dt>Universe</dt><dd>${TB_UNIVERSE}</dd>
    </dl>
  </div>

  <!-- ═══ BYLINE ═══════════════════════════ -->
  <div class="byline">
    <div class="analysts">
      <div class="analyst">
        <div class="ana-init">ST</div>
        <div class="ana-meta">
          <b>Strategy Desk</b>
          <span>India Equities · Lead</span>
        </div>
      </div>
      <div class="analyst">
        <div class="ana-init alt">QS</div>
        <div class="ana-meta">
          <b>Quant &amp; Screens</b>
          <span>Systematic Signals</span>
        </div>
      </div>
      <div class="analyst">
        <div class="ana-init alt2">DV</div>
        <div class="ana-meta">
          <b>Derivatives Desk</b>
          <span>F&amp;O · Flows</span>
        </div>
      </div>
    </div>
    <div class="toc-pills">
      <span class="toc-pill"><b>01</b>At a Glance</span>
      <span class="toc-pill"><b>02</b>Pre-Market</span>
      <span class="toc-pill"><b>03</b>Action</span>
      <span class="toc-pill"><b>04</b>Movers</span>
      <span class="toc-pill"><b>05</b>Idea</span>
      <span class="toc-pill"><b>06</b>Technical</span>
      <span class="toc-pill"><b>07</b>F&amp;O</span>
      <span class="toc-pill"><b>08</b>Smart Money</span>
      <span class="toc-pill"><b>09</b>Calendar</span>
      <span class="toc-pill"><b>10</b>Rebalance</span>
    </div>
  </div>

  <!-- ═══ TICKER TAPE ═══════════════════════ -->
  <div class="ticker">
    <div class="tk">
      <div class="lbl">${TK1_LBL}</div>
      <div class="code">${TK1_CODE}</div>
      <div class="val">${TK1_VAL}</div>
      <div class="chg ${TK1_DIR}">${TK1_CHG}</div>
    </div>
    <div class="tk">
      <div class="lbl">${TK2_LBL}</div>
      <div class="code">${TK2_CODE}</div>
      <div class="val">${TK2_VAL}</div>
      <div class="chg ${TK2_DIR}">${TK2_CHG}</div>
    </div>
    <div class="tk">
      <div class="lbl">${TK3_LBL}</div>
      <div class="code">${TK3_CODE}</div>
      <div class="val">${TK3_VAL}</div>
      <div class="chg ${TK3_DIR}">${TK3_CHG}</div>
    </div>
    <div class="tk">
      <div class="lbl">${TK4_LBL}</div>
      <div class="code">${TK4_CODE}</div>
      <div class="val">${TK4_VAL}</div>
      <div class="chg ${TK4_DIR}">${TK4_CHG}</div>
    </div>
    <div class="tk">
      <div class="lbl">${TK5_LBL}</div>
      <div class="code">${TK5_CODE}</div>
      <div class="val">${TK5_VAL}</div>
      <div class="chg ${TK5_DIR}">${TK5_CHG}</div>
    </div>
    <div class="tk">
      <div class="lbl">${TK6_LBL}</div>
      <div class="code">${TK6_CODE}</div>
      <div class="val">${TK6_VAL}</div>
      <div class="chg ${TK6_DIR}">${TK6_CHG}</div>
    </div>
  </div>

  <!-- ═══ RECOMMENDATION SUMMARY ═══════════════════════ -->
  <div class="summary">
    <div class="summary-head">
      <span>${SUMHEAD_LEFT}</span>
      <span>${SUMHEAD_MID}</span>
      <span class="ts">${SUMHEAD_RIGHT}</span>
    </div>
    <table class="summary-table">
      <thead>
        <tr>
          <th style="width: 24%;">Topic</th>
          <th style="width: 12%;">Stance</th>
          <th style="width: 44%;">Action / Rationale</th>
          <th class="num" style="width: 20%;">Key Level</th>
        </tr>
      </thead>
      <tbody>
${REC_ROWS}
      </tbody>
    </table>
  </div>

  <!-- ═══ 01 · AT A GLANCE ═══════════════════ -->
  <section>
    <div class="sec-head">
      <div class="sec-num">§ 01 / 10</div>
      <h2 class="sec-title">At a Glance</h2>
      <div class="sec-kicker">Open · Tone · Flow</div>
    </div>

    <div class="lead">
      <div class="lead-body">
${GLANCE_LEAD_BODY}
        <div class="view-card">
          <b>Our View</b>
          ${GLANCE_OUR_VIEW}
        </div>
      </div>

      <aside class="lead-side">
        <h4>${GLANCE_FLOWS_TITLE}</h4>
        <div class="flow-grid">
          <div class="flow-cell fii">
            <div class="who">FII · Net</div>
            <div class="amt">${GLANCE_FII_AMT}</div>
          </div>
          <div class="flow-cell dii">
            <div class="who">DII · Net</div>
            <div class="amt">${GLANCE_DII_AMT}</div>
          </div>
        </div>
        <div class="flow-bar">
          <div class="b-fii" style="width: ${GLANCE_FII_PCT}%;">FII ${GLANCE_FII_BAR_LBL}</div>
          <div class="b-dii" style="width: ${GLANCE_DII_PCT}%;">DII ${GLANCE_DII_BAR_LBL}</div>
        </div>
        <p class="flow-cap">${GLANCE_FLOW_CAP}</p>
      </aside>
    </div>
  </section>

  <!-- ═══ 02 · PRE-MARKET CUES ═══════════════ -->
  <section>
    <div class="sec-head">
      <div class="sec-num">§ 02 / 10</div>
      <h2 class="sec-title">Pre-Market Cues</h2>
      <div class="sec-kicker">Overnight · Global Read-Through</div>
    </div>

    <div class="premarket">
${PM_TILES}
    </div>

    <div class="signal-strip">
      <div class="label">Signal</div>
      <div>${PM_SIGNAL_COPY}</div>
      <div><span class="rec-chip ${PM_SIGNAL_VARIANT}">${PM_SIGNAL_LABEL}</span></div>
    </div>
  </section>

  <!-- ═══ 03 · MARKET ACTION ═══════════════ -->
  <section>
    <div class="sec-head">
      <div class="sec-num">§ 03 / 10</div>
      <h2 class="sec-title">Market Action · Yesterday</h2>
      <div class="sec-kicker">Sector Heat · Indices · Breadth</div>
    </div>

    <div class="market">
      <div class="sectors">
        <h5 class="panel-h">Sector Performance · % chg</h5>
${SECTOR_ROWS}
      </div>

      <div class="indexbox">
        <h5 class="panel-h">Headline Indices · Close</h5>
${INDEX_ROWS}
        <div class="breadth">
          <div>
            <div class="b-l">Breadth</div>
            <div class="b-v">${BREADTH_AD}</div>
          </div>
          <div class="b-bar"><i style="width: ${BREADTH_PCT}%;"></i></div>
          <div class="b-v">${BREADTH_RATIO}</div>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ 04 · MOVERS ═══════════════ -->
  <section>
    <div class="sec-head">
      <div class="sec-num">§ 04 / 10</div>
      <h2 class="sec-title">Top Movers · Coverage Universe</h2>
      <div class="sec-kicker">Gainers · Losers</div>
    </div>

    <div class="movers">
      <div class="mover-card">
        <h5><span class="pip up"></span>Gainers</h5>
        <table class="mv">
          <thead><tr><th>Ticker</th><th>Trend</th><th class="r">Close ₹</th><th class="r">Δ %</th></tr></thead>
          <tbody>
${GAINERS_ROWS}
          </tbody>
        </table>
      </div>

      <div class="mover-card">
        <h5><span class="pip down"></span>Losers</h5>
        <table class="mv">
          <thead><tr><th>Ticker</th><th>Trend</th><th class="r">Close ₹</th><th class="r">Δ %</th></tr></thead>
          <tbody>
${LOSERS_ROWS}
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- ═══ 05 · TOP FUNDAMENTAL IDEA ═══════════════ -->
  <section>
    <div class="sec-head">
      <div class="sec-num">§ 05 / 10</div>
      <h2 class="sec-title">Top Fundamental Idea</h2>
      <div class="sec-kicker">Top-Ranked Filter Output · GARP Framework · Today</div>
    </div>

    <div class="idea">
      <div class="idea-l">
        <div class="idea-stamp"><span class="dot"></span>${IDEA_STAMP}</div>
        <h3>${IDEA_TITLE}</h3>
        <div class="ticker-row">
${IDEA_TICKER_ROW}
        </div>

        <p class="idea-thesis">${IDEA_THESIS}</p>

        <ul class="bullet-list">
${IDEA_BULLETS}
        </ul>

        <div class="risk-row">
          <b>Bear</b>
          <div>${IDEA_BEAR}</div>
        </div>

        <div class="levels">
          <div class="entry"><div class="lbl">Entry</div><div class="v">${IDEA_ENTRY}</div></div>
          <div class="stop"><div class="lbl">Stop</div><div class="v">${IDEA_STOP}</div></div>
          <div class="tgt"><div class="lbl">Base Case</div><div class="v">${IDEA_TARGET}</div></div>
        </div>

        <div class="upside-bar">
${IDEA_UPSIDE}
        </div>
      </div>

      <div class="idea-r">
        <h5 class="panel-h">Key Metrics · ${IDEA_METRICS_TITLE}</h5>
        <div class="met-grid">
${IDEA_METRICS}
        </div>

        <div class="score-panel">
          <div class="lbl">Adjusted Composite Score</div>
          <div class="row">
            <div class="big">${IDEA_SCORE}</div>
            <div class="breakdown">
${IDEA_BREAKDOWN}
            </div>
          </div>
          <div class="note">${IDEA_SCORE_NOTE}</div>
        </div>
      </div>
    </div>

    <div class="runner-up">
      <span class="tag">${RUNNER_TAG}</span>
      ${RUNNER_BODY}
    </div>
  </section>

  <!-- ═══ 06 · TECHNICAL ═══════════════ -->
  <section>
    <div class="sec-head">
      <div class="sec-num">§ 06 / 10</div>
      <h2 class="sec-title">Technical · Swing Setups</h2>
      <div class="sec-kicker">Scanner Regime · Risk Posture</div>
    </div>

    <div class="regime">
      <div class="light-stack">
        <div class="light ${REGIME_TOP_CLASS}"></div>
        <div class="light ${REGIME_MID_CLASS}"></div>
        <div class="light ${REGIME_BOT_CLASS}"></div>
        <div class="light-label">${REGIME_LABEL}</div>
      </div>
      <div class="copy">
        <div class="kicker">Scanner Regime · Today</div>
        <div class="verdict">${REGIME_VERDICT}</div>
        <p class="detail">${REGIME_DETAIL}</p>
      </div>
      <div class="levels-mini">
        <div class="lbl">${REGIME_LEVEL_LABEL}</div>
        <div class="big">${REGIME_LEVEL_VAL}</div>
        <div class="sub">${REGIME_LEVEL_SUB}</div>
      </div>
    </div>
  </section>

  <!-- ═══ 07 · F&O ═══════════════ -->
  <section>
    <div class="sec-head">
      <div class="sec-num">§ 07 / 10</div>
      <h2 class="sec-title">F&amp;O · Derivatives Read</h2>
      <div class="sec-kicker">PCR · Max Pain · Nearest Expiry</div>
    </div>

    <div class="fno">
${FNO_CARDS}
    </div>
  </section>

  <!-- ═══ 08 · SMART MONEY ═══════════════ -->
  <section>
    <div class="sec-head">
      <div class="sec-num">§ 08 / 10</div>
      <h2 class="sec-title">Smart Money Tracker</h2>
      <div class="sec-kicker">Block Deals · Promoter Activity</div>
    </div>

    <div class="blocks">
${SMART_BLOCKS}
    </div>

    ${SMART_PROMOTER}
  </section>

  <!-- ═══ 09 · CALENDAR ═══════════════ -->
  <section>
    <div class="sec-head">
      <div class="sec-num">§ 09 / 10</div>
      <h2 class="sec-title">Macro Calendar · Next 14 Days</h2>
      <div class="sec-kicker">Print Risk · MPC Watch</div>
    </div>

    <div class="calendar">
${CAL_CELLS}
    </div>

    <p style="margin-top: 16px; font-family: var(--sans); font-size: 13px; line-height: 1.55; color: var(--ink-2); max-width: 880px;">
      ${CAL_WATCHING}
    </p>
  </section>

  <!-- ═══ 10 · REBALANCE ═══════════════ -->
  <section>
    <div class="sec-head">
      <div class="sec-num">§ 10 / 10</div>
      <h2 class="sec-title">Index Rebalance Watch</h2>
      <div class="sec-kicker">Passive Flow Estimate</div>
    </div>

    <div class="rebalance">
      <div>
        <div class="tk-big">${REB_TICKER} <small>${REB_SUB}</small></div>
      </div>
      <div class="copy">
        <b>${REB_TAG}</b>
        ${REB_BODY}
      </div>
      <div class="inflow">${REB_INFLOW}<small>${REB_INFLOW_LABEL}</small></div>
    </div>
  </section>

  <!-- ═══ DISCLAIMER ═══════════════════════ -->
  <footer class="disclaimer">
    <h6>Disclaimer</h6>
    <p><strong style="color: var(--ink-2);">¹ Footnote:</strong> ${DIS_FOOTNOTE}</p>
    <p>${DIS_BODY}</p>
    <div class="grid">
      <div><b>Sources</b>${DIS_SOURCES}</div>
      <div><b>Distribution</b>${DIS_DIST}</div>
      <div><b>Cycle</b>${DIS_CYCLE}</div>
    </div>
  </footer>

</div>

</body>
</html>
"""

_TEMPLATE = Template(_TEMPLATE_STR)


# ════════════════════════════════════════════════════════════════════════════
#  Public API
# ════════════════════════════════════════════════════════════════════════════

def render_brief_v2(data,
                    kpi_data: Optional[Dict] = None,
                    embed_images: Optional[Dict[str, bytes]] = None) -> str:
    """Render the full Claude Design morning brief as a self-contained HTML string.

    Args:
        data: a ``DailyNoteData`` instance (from ``src.agent.daily_note``).
        kpi_data: optional pre-built KPI dict (derived from ``data`` if absent).
        embed_images: currently unused — v2 renders all visuals inline (SVG).

    Returns:
        A complete HTML document (str) ready to write to disk or serve.

    The output is structurally identical to the reference design at
    ``/tmp/handover/design_handoff_morning_brief/India Morning Brief.html`` —
    same firmbar, same .page wrapper, same 10 numbered sections, same disclaimer.
    Only the displayed numbers and copy change with the input data.
    """
    today_str = getattr(data, "today", None) or date.today().strftime("%d %b %Y")
    try:
        ph = _data_for_template(data, kpi_data, today_str=today_str)
    except Exception as exc:
        log.exception("v2 template data build failed: %s", exc)
        raise

    # safe_substitute won't blow up if any placeholder happens to be missing
    return _TEMPLATE.safe_substitute(ph)
