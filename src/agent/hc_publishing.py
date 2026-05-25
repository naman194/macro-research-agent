"""High Conviction publishing workflow.

Three jobs:
  1. Daily qualification log — every run, snapshot which names CURRENTLY qualify.
     SQLite-backed. Lets us compute "newly qualified today" / "dropped out today".
  2. Watchlist — user-curated set of names to track regardless of HC status.
     Persistent. Shows current HC status + last-seen-qualified date.
  3. Email-ready HTML brief — auto-generated daily output suitable for emailing
     to institutional clients. Self-contained, mobile-friendly, branded.

Plus a `daily_run()` entry point for cron-style automation.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import CACHE_DIR, DEFAULT_UNIVERSE
from src.screens.high_conviction import HighConvictionPick, evaluate_high_conviction

log = logging.getLogger(__name__)

DB_PATH = CACHE_DIR / "hc_publishing.sqlite"


# ============================================================
# DB
# ============================================================

@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS qualifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                name TEXT,
                sector TEXT,
                conviction_score REAL,
                entry_price REAL,
                technical_setup TEXT,
                net_overlay REAL,
                logged_at TEXT NOT NULL,
                UNIQUE(snapshot_date, ticker)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker TEXT PRIMARY KEY,
                added_at TEXT NOT NULL,
                notes TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS ix_qual_date ON qualifications(snapshot_date)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_qual_ticker ON qualifications(ticker)")


# ============================================================
# Watchlist API
# ============================================================

def watchlist_add(ticker: str, notes: str = "") -> bool:
    _init_db()
    with _conn() as c:
        try:
            c.execute("INSERT OR REPLACE INTO watchlist (ticker, added_at, notes) "
                      "VALUES (?, ?, ?)",
                      (ticker.upper(), datetime.utcnow().isoformat(), notes))
            return True
        except sqlite3.IntegrityError:
            return False


def watchlist_remove(ticker: str) -> bool:
    _init_db()
    with _conn() as c:
        cur = c.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),))
        return cur.rowcount > 0


def watchlist_all() -> List[Dict[str, Any]]:
    _init_db()
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM watchlist ORDER BY added_at DESC"
        ).fetchall()]


# ============================================================
# Qualification log
# ============================================================

def log_qualifications(picks: List[HighConvictionPick]) -> int:
    _init_db()
    today = date.today().isoformat()
    now = datetime.utcnow().isoformat()
    logged = 0
    with _conn() as c:
        for p in picks:
            try:
                c.execute(
                    "INSERT OR IGNORE INTO qualifications "
                    "(snapshot_date, ticker, name, sector, conviction_score, "
                    "entry_price, technical_setup, net_overlay, logged_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (today, p.ticker, p.name, p.sector, p.conviction_score,
                     p.entry, p.technical_setup, p.net_overlay, now)
                )
                if c.total_changes:
                    logged += 1
            except sqlite3.IntegrityError:
                pass
    return logged


def changes_vs_yesterday(today_tickers: List[str]) -> Dict[str, List[str]]:
    """Compare today's qualifying set to yesterday's (latest prior date in DB)."""
    _init_db()
    today_set = set(t.upper() for t in today_tickers)
    today = date.today().isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT MAX(snapshot_date) AS d FROM qualifications WHERE snapshot_date < ?",
            (today,)
        ).fetchone()
        prior_date = row["d"] if row else None
        if not prior_date:
            return {"newly_qualified": list(today_set),
                    "dropped_out": [], "still_qualified": [],
                    "prior_snapshot_date": None}
        rows = c.execute(
            "SELECT ticker FROM qualifications WHERE snapshot_date = ?",
            (prior_date,)
        ).fetchall()
    prior_set = set(r["ticker"] for r in rows)
    return {
        "newly_qualified": sorted(today_set - prior_set),
        "dropped_out": sorted(prior_set - today_set),
        "still_qualified": sorted(today_set & prior_set),
        "prior_snapshot_date": prior_date,
    }


def history_for_ticker(ticker: str, last_n_days: int = 90) -> List[Dict[str, Any]]:
    _init_db()
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM qualifications WHERE ticker = ? "
            "ORDER BY snapshot_date DESC LIMIT ?", (ticker.upper(), last_n_days)
        ).fetchall()]


def latest_picks_from_log(snapshot_date: Optional[str] = None) -> List[Dict[str, Any]]:
    _init_db()
    with _conn() as c:
        if snapshot_date is None:
            row = c.execute("SELECT MAX(snapshot_date) AS d FROM qualifications").fetchone()
            snapshot_date = row["d"] if row else None
        if not snapshot_date:
            return []
        return [dict(r) for r in c.execute(
            "SELECT * FROM qualifications WHERE snapshot_date = ? "
            "ORDER BY conviction_score DESC", (snapshot_date,)
        ).fetchall()]


# ============================================================
# Email-ready HTML brief
# ============================================================

def generate_hc_email_html(picks: List[HighConvictionPick],
                            changes: Dict[str, List[str]]) -> str:
    """Self-contained HTML — paste body into Gmail / Outlook, or send as attachment."""
    today_str = date.today().strftime("%A, %d %b %Y")
    n = len(picks)

    BRAND = "#0a3d62"
    INK = "#1a1a1a"
    MUTED = "#6b7280"
    GREEN = "#0a7e2f"
    RED = "#b71c1c"
    LIGHT = "#f5f7fa"
    BORDER = "#e2e8f0"

    # Changes badges
    changes_html = ""
    nq = changes.get("newly_qualified", [])
    do = changes.get("dropped_out", [])
    if nq or do:
        nq_str = ", ".join(f"<b>{t}</b>" for t in nq) if nq else "<em>none</em>"
        do_str = ", ".join(f"<b>{t}</b>" for t in do) if do else "<em>none</em>"
        changes_html = f"""
        <div style="margin:16px 0;padding:14px;background:{LIGHT};border-radius:8px;
                    border-left:4px solid {BRAND};">
            <div style="font-weight:700;color:{BRAND};margin-bottom:8px;">📌 Changes vs prior session</div>
            <div style="color:{GREEN};margin-bottom:4px;">🟢 Newly qualified: {nq_str}</div>
            <div style="color:{RED};">🔴 Dropped out: {do_str}</div>
        </div>
        """

    if n == 0:
        picks_html = f"""
        <div style="padding:24px;text-align:center;color:{MUTED};
                    background:{LIGHT};border-radius:8px;">
            <h3 style="color:{INK};margin:0 0 8px;">No High Conviction picks today</h3>
            <p>Either macro regime is risk-off, or no name passed the 6-layer filter.
               This is correct conservative behaviour — quality, not quantity.</p>
        </div>
        """
    else:
        pick_cards = []
        for p in picks:
            why_bullets = "".join(f"<li style='margin:3px 0;'>{w}</li>"
                                  for w in p.why_high_conviction[:5])
            stop_pct = (1 - p.stop_loss_suggested / p.entry) * 100
            pick_cards.append(f"""
            <div style="background:white;border:1px solid {BORDER};border-radius:8px;
                        padding:18px;margin-bottom:14px;
                        border-left:4px solid {BRAND};">
                <div style="display:flex;justify-content:space-between;align-items:baseline;
                            margin-bottom:8px;">
                    <div>
                        <span style="font-size:18px;font-weight:700;color:{BRAND};">{p.ticker}</span>
                        <span style="color:{MUTED};font-size:13px;margin-left:8px;">{p.name}</span>
                    </div>
                    <div style="background:{BRAND};color:white;padding:4px 10px;
                                border-radius:4px;font-size:12px;font-weight:700;">
                        Conviction {p.conviction_score:.0f}/100
                    </div>
                </div>
                <div style="display:flex;gap:14px;flex-wrap:wrap;
                            font-size:12px;color:{MUTED};margin:6px 0 12px;">
                    <span><b style="color:{INK};">{p.sector}</b></span>
                    <span>ROCE <b style="color:{INK};">{p.roce:.0f}%</b></span>
                    <span>ROE <b style="color:{INK};">{p.roe:.0f}%</b></span>
                    <span>D/E <b style="color:{INK};">{p.debt_to_equity:.2f}</b></span>
                    <span>3y PG <b style="color:{INK};">{p.profit_cagr_3y:.0f}%</b></span>
                    <span>P/E <b style="color:{INK};">{p.pe:.1f}</b></span>
                    <span>Mkt cap <b style="color:{INK};">₹{p.market_cap_cr/1000:.1f}k Cr</b></span>
                </div>
                <ul style="margin:6px 0;padding-left:22px;font-size:13px;color:{INK};">{why_bullets}</ul>
                <div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:12px;
                            padding:10px;background:{LIGHT};border-radius:6px;font-size:13px;">
                    <div><b>Entry:</b> ₹{p.entry:.1f}</div>
                    <div><b>Stop loss:</b> ₹{p.stop_loss_suggested:.1f}
                         <span style="color:{RED};">(-{stop_pct:.1f}%)</span></div>
                    <div><b>Setup:</b> {p.technical_setup}</div>
                    <div><b>Hold:</b> 6-12 months · <b>Size:</b> 3-5%</div>
                </div>
            </div>
            """)
        picks_html = "".join(pick_cards)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>High Conviction Daily — {today_str}</title>
</head>
<body style="margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:{LIGHT};color:{INK};">
    <div style="max-width:760px;margin:0 auto;">
        <div style="background:linear-gradient(90deg,{BRAND},#1d5b8a);color:white;
                    padding:22px 28px;border-radius:10px 10px 0 0;
                    display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
            <div>
                <h1 style="margin:0;font-size:22px;font-weight:700;">🎯 High Conviction Daily</h1>
                <div style="font-size:10px;letter-spacing:1px;opacity:0.85;
                            margin-top:4px;font-weight:600;">
                    INSTITUTIONAL RESEARCH · 6-LAYER COMPOSITE FILTER
                </div>
            </div>
            <div style="font-size:13px;opacity:0.95;">{today_str}</div>
        </div>
        <div style="background:white;padding:24px 28px;border-radius:0 0 10px 10px;
                    box-shadow:0 1px 4px rgba(0,0,0,0.04);">
            <p style="color:{MUTED};font-size:13px;margin:0 0 8px;">
                {n} name(s) passed all six layers: fundamental quality (ROCE>=15, ROE>=15,
                D/E<=0.5, profit CAGR 3y>=10), structural overlay (catalysts &gt;= 8 pts,
                sector penalty &lt;= 22.5), technical setup confirmation, relative strength,
                sentiment filter, macro regime.
            </p>
            {changes_html}
            <h2 style="font-size:17px;color:{BRAND};margin:24px 0 14px;
                       padding:6px 0 6px 12px;border-left:4px solid {BRAND};background:#fafbfd;">
                Today's Picks ({n})
            </h2>
            {picks_html}
            <div style="margin-top:30px;padding-top:18px;border-top:1px solid {BORDER};
                        font-size:11px;color:{MUTED};text-align:center;">
                <b>Recommended hold:</b> 6-12 months · <b>Position size:</b> 3-5% per pick<br/>
                <b>Exit triggers:</b> -15% stop OR thesis breaks (overlay flips negative) OR hold horizon completes<br/><br/>
                For institutional use only · Not investment advice · Verify all figures before action<br/>
                Generated {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC by Macro Research Agent
            </div>
        </div>
    </div>
</body>
</html>
"""


# ============================================================
# Daily run — entry point for cron / on-demand
# ============================================================

def daily_run(universe: Optional[List[str]] = None) -> Dict[str, Any]:
    """One-shot: evaluate HC, log qualifications, compute changes, generate brief.
    Returns dict suitable for UI rendering AND for cron output."""
    universe = universe or DEFAULT_UNIVERSE
    picks = evaluate_high_conviction(universe, require_macro_uptrend=True)

    log_qualifications(picks)
    today_tickers = [p.ticker for p in picks]
    changes = changes_vs_yesterday(today_tickers)

    html = generate_hc_email_html(picks, changes)
    return {
        "snapshot_date": date.today().isoformat(),
        "picks_count": len(picks),
        "picks": [asdict(p) for p in picks],
        "changes": changes,
        "email_html": html,
    }
