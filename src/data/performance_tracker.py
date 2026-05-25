"""Screen performance tracker — forward journal + lookback proxy.

Two surfaces:
  1. **Forward journal**: every time a screen runs and produces top picks, we log them
     with date + entry price. Later, when realized prices come in, we compute hit-rate
     and average return per N-day window. SQLite-backed; persists across sessions.
  2. **Lookback proxy**: for current screen candidates, show what return they would
     have delivered if entered N days ago (1m / 3m / 6m / 1y) — gives a quick
     "would-have-worked" view even before forward data accumulates.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import CACHE_DIR
from src.data.prices import PricesAdapter

log = logging.getLogger(__name__)

DB_PATH = CACHE_DIR / "performance.sqlite"


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
            CREATE TABLE IF NOT EXISTS picks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pick_date TEXT NOT NULL,
                framework TEXT NOT NULL,
                ticker TEXT NOT NULL,
                rank INTEGER,
                score REAL,
                entry_price REAL,
                logged_at TEXT NOT NULL,
                UNIQUE(pick_date, framework, ticker)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS ix_picks_date ON picks(pick_date)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_picks_fw ON picks(framework)")
        # Structural-risk + catalyst flag snapshots — for retrospective validation
        # of judgment data over time.
        c.execute("""
            CREATE TABLE IF NOT EXISTS flag_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                sector TEXT,
                raw_score REAL,
                sector_penalty REAL,
                company_penalty REAL,
                total_penalty REAL,
                sector_catalyst REAL,
                company_catalyst REAL,
                total_catalyst REAL,
                adjusted_score REAL,
                entry_price REAL,
                logged_at TEXT NOT NULL,
                UNIQUE(snapshot_date, ticker)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS ix_flag_date ON flag_snapshots(snapshot_date)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_flag_ticker ON flag_snapshots(ticker)")


# ---- Forward journal ----

def log_picks(framework: str, picks: List[Dict[str, Any]],
              prices_adapter: Optional[PricesAdapter] = None) -> int:
    """Log a batch of screener picks for today. Idempotent — won't double-log a name."""
    _init_db()
    prices_adapter = prices_adapter or PricesAdapter()
    today = date.today().isoformat()
    logged = 0
    with _conn() as c:
        for i, p in enumerate(picks, start=1):
            ticker = p.get("ticker")
            if not ticker:
                continue
            # Fetch entry price (today's close)
            entry = None
            try:
                hist = prices_adapter.history(f"{ticker}.NS", period="5d")
                if not hist.empty:
                    entry = float(hist["Close"].iloc[-1])
            except Exception:
                pass
            try:
                c.execute(
                    "INSERT OR IGNORE INTO picks (pick_date, framework, ticker, rank, "
                    "score, entry_price, logged_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (today, framework, ticker, i, p.get("score"), entry,
                     datetime.utcnow().isoformat()),
                )
                if c.total_changes:
                    logged += 1
            except sqlite3.IntegrityError:
                pass
    return logged


def journal_summary(framework: Optional[str] = None) -> pd.DataFrame:
    """Return all logged picks with realized N-day returns vs current price."""
    _init_db()
    query = "SELECT * FROM picks"
    params: tuple = ()
    if framework:
        query += " WHERE framework = ?"
        params = (framework,)
    query += " ORDER BY pick_date DESC, rank ASC"
    with _conn() as c:
        rows = [dict(r) for r in c.execute(query, params).fetchall()]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)

    # Compute realized return vs current price
    prices = PricesAdapter()
    cur_prices: Dict[str, float] = {}
    for t in df["ticker"].unique():
        try:
            h = prices.history(f"{t}.NS", period="5d")
            if not h.empty:
                cur_prices[t] = float(h["Close"].iloc[-1])
        except Exception:
            pass
    df["current_price"] = df["ticker"].map(cur_prices)
    df["return_pct"] = ((df["current_price"] / df["entry_price"] - 1) * 100).round(2)
    df["days_held"] = (pd.Timestamp.utcnow().normalize().date() -
                       pd.to_datetime(df["pick_date"]).dt.date).dt.days
    return df


def journal_hit_rate(framework: Optional[str] = None,
                     min_days_held: int = 30) -> Dict[str, Any]:
    """Aggregate stats: picks with >= min_days_held — win rate, avg return, distribution."""
    df = journal_summary(framework)
    if df.empty:
        return {"total_picks": 0, "evaluable_picks": 0, "framework": framework}
    evaluable = df[df["days_held"] >= min_days_held].dropna(subset=["return_pct"])
    if evaluable.empty:
        return {"total_picks": len(df), "evaluable_picks": 0,
                "framework": framework,
                "note": f"No picks held >= {min_days_held} days yet — log will fill in."}
    wins = (evaluable["return_pct"] > 0).sum()
    losses = (evaluable["return_pct"] <= 0).sum()
    return {
        "framework": framework,
        "total_picks": int(len(df)),
        "evaluable_picks": int(len(evaluable)),
        "win_rate_pct": round(wins / len(evaluable) * 100, 1),
        "wins": int(wins),
        "losses": int(losses),
        "avg_return_pct": round(evaluable["return_pct"].mean(), 2),
        "median_return_pct": round(evaluable["return_pct"].median(), 2),
        "best_pick": (evaluable.sort_values("return_pct", ascending=False)
                      .iloc[0].to_dict()),
        "worst_pick": (evaluable.sort_values("return_pct").iloc[0].to_dict()),
    }


# ---- Lookback proxy ----

def log_flag_snapshot(candidates: List[Dict[str, Any]],
                      prices_adapter: Optional[PricesAdapter] = None) -> int:
    """Log structural-flag snapshot for every screened name. Idempotent per day-ticker."""
    _init_db()
    prices_adapter = prices_adapter or PricesAdapter()
    today = date.today().isoformat()
    logged = 0
    with _conn() as c:
        for c_row in candidates:
            ticker = c_row.get("ticker")
            if not ticker:
                continue
            entry = None
            try:
                h = prices_adapter.history(f"{ticker}.NS", period="5d")
                if not h.empty:
                    entry = float(h["Close"].iloc[-1])
            except Exception:
                pass
            try:
                c.execute(
                    "INSERT OR IGNORE INTO flag_snapshots (snapshot_date, ticker, sector, "
                    "raw_score, sector_penalty, company_penalty, total_penalty, "
                    "sector_catalyst, company_catalyst, total_catalyst, adjusted_score, "
                    "entry_price, logged_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (today, ticker, c_row.get("sector"),
                     c_row.get("raw_score"), c_row.get("sector_penalty"),
                     c_row.get("company_penalty"), c_row.get("structural_penalty"),
                     c_row.get("sector_catalyst"), c_row.get("company_catalyst"),
                     c_row.get("catalyst_bonus"), c_row.get("score"),
                     entry, datetime.utcnow().isoformat()),
                )
                if c.total_changes:
                    logged += 1
            except sqlite3.IntegrityError:
                pass
    return logged


def flag_retrospective(min_days_held: int = 30) -> Dict[str, Any]:
    """Validate our risk judgment: do high-penalty names actually underperform?

    Splits snapshots into low / medium / high penalty buckets, computes realized
    return for each. If our judgment is right, high-penalty names should have
    lower realized returns on average."""
    _init_db()
    with _conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM flag_snapshots ORDER BY snapshot_date DESC"
        ).fetchall()]
    if not rows:
        return {"snapshots": 0, "evaluable": 0,
                "note": "No flag snapshots logged yet — will accumulate as you generate briefs."}
    df = pd.DataFrame(rows)
    df["snapshot_date_dt"] = pd.to_datetime(df["snapshot_date"])
    df["days_held"] = (pd.Timestamp.utcnow().normalize() - df["snapshot_date_dt"]).dt.days
    evaluable = df[df["days_held"] >= min_days_held].copy()
    if evaluable.empty:
        return {"snapshots": int(len(df)), "evaluable": 0,
                "note": f"No snapshots ≥{min_days_held} days old yet."}

    # Pull current prices, compute realized returns
    prices = PricesAdapter()
    cur = {}
    for t in evaluable["ticker"].unique():
        try:
            h = prices.history(f"{t}.NS", period="5d")
            if not h.empty:
                cur[t] = float(h["Close"].iloc[-1])
        except Exception:
            pass
    evaluable["current_price"] = evaluable["ticker"].map(cur)
    evaluable = evaluable.dropna(subset=["current_price", "entry_price"])
    evaluable["return_pct"] = ((evaluable["current_price"] / evaluable["entry_price"] - 1) * 100).round(2)

    if evaluable.empty:
        return {"snapshots": int(len(df)), "evaluable": 0,
                "note": "Prices unavailable for evaluable snapshots."}

    # Bucket by total_penalty
    def bucket(p):
        if p is None or pd.isna(p): return "unknown"
        if p < 15: return "low (<15)"
        if p < 30: return "medium (15-30)"
        return "high (≥30)"
    evaluable["penalty_bucket"] = evaluable["total_penalty"].apply(bucket)

    bucket_stats = evaluable.groupby("penalty_bucket").agg(
        n=("ticker", "count"),
        avg_return_pct=("return_pct", "mean"),
        median_return_pct=("return_pct", "median"),
        win_rate_pct=("return_pct", lambda s: (s > 0).mean() * 100),
    ).round(2).reset_index().to_dict("records")

    # Catalyst bucket similarly
    def cat_bucket(b):
        if b is None or pd.isna(b): return "unknown"
        if b < 5: return "low (<5)"
        if b < 15: return "medium (5-15)"
        return "high (≥15)"
    evaluable["catalyst_bucket"] = evaluable["total_catalyst"].apply(cat_bucket)
    cat_stats = evaluable.groupby("catalyst_bucket").agg(
        n=("ticker", "count"),
        avg_return_pct=("return_pct", "mean"),
        win_rate_pct=("return_pct", lambda s: (s > 0).mean() * 100),
    ).round(2).reset_index().to_dict("records")

    return {
        "snapshots": int(len(df)),
        "evaluable": int(len(evaluable)),
        "min_days_held": min_days_held,
        "penalty_bucket_stats": bucket_stats,
        "catalyst_bucket_stats": cat_stats,
        "interpretation": (
            "If our judgment is correct, the 'high (≥30)' penalty bucket should have "
            "the LOWEST avg return + win rate, and 'high (≥15)' catalyst bucket should "
            "have the HIGHEST. Diverging from that signals our flags need re-calibration."
        ),
    }


def lookback_returns(tickers: List[str], horizons_days: List[int] = [30, 90, 180, 365]
                     ) -> pd.DataFrame:
    """For each ticker, return the realized return if entered N days ago and held to today."""
    prices = PricesAdapter()
    rows = []
    for t in tickers:
        try:
            df = prices.history(f"{t}.NS", period="400d")
            if df.empty or len(df) < max(horizons_days):
                continue
            today_close = float(df["Close"].iloc[-1])
            row: Dict[str, Any] = {"ticker": t, "current_price": round(today_close, 2)}
            for h in horizons_days:
                if len(df) > h:
                    past = float(df["Close"].iloc[-h - 1])
                    if past > 0:
                        row[f"return_{h}d_pct"] = round((today_close / past - 1) * 100, 2)
                        row[f"entry_{h}d_ago"] = round(past, 2)
            rows.append(row)
        except Exception as exc:
            log.warning("lookback %s failed: %s", t, exc)
    return pd.DataFrame(rows)


def lookback_aggregate(tickers: List[str], horizons_days: List[int] = [30, 90, 180, 365]
                       ) -> Dict[str, Any]:
    """Aggregate win-rate and avg return across a list of tickers at each horizon."""
    df = lookback_returns(tickers, horizons_days)
    if df.empty:
        return {"n_tickers": 0}
    out: Dict[str, Any] = {"n_tickers": int(len(df)), "by_horizon": {}}
    for h in horizons_days:
        col = f"return_{h}d_pct"
        if col not in df.columns:
            continue
        series = df[col].dropna()
        if series.empty:
            continue
        out["by_horizon"][f"{h}d"] = {
            "evaluable": int(len(series)),
            "win_rate_pct": round((series > 0).mean() * 100, 1),
            "avg_return_pct": round(series.mean(), 2),
            "median_return_pct": round(series.median(), 2),
            "best": round(series.max(), 2),
            "worst": round(series.min(), 2),
        }
    return out
