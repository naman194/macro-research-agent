"""screener.in Premium adapter — uses authenticated session for historical financials.

screener.in's free tier:
  - Public company pages with current ratios + last 10 years of P&L / BS in HTML tables
  - Often 404s on some tickers (slug variants like TATAMOTORS, LTIM, AARTI)
  - Quarterly results visible on page but harder to parse over multiple periods

screener.in Premium tier (~₹2,500/yr):
  - All slugs resolve correctly (no more 404s)
  - 10-year historical financials available via cleaner endpoints
  - Watchlists, alerts, export to Excel
  - "Custom queries" — can build screens server-side

This adapter:
  - When SCREENER_PREMIUM_SESSIONID is set in .env, uses authenticated session
    for any company page (resolves slug issues automatically since premium tier
    handles redirects)
  - Exposes `historical_financials(ticker)` that returns 10y of P&L + BS as DataFrames
  - Falls back to free adapter when no key — graceful degradation
  - Status helper `is_premium_active()` for UI indicator

To use: subscribe at https://www.screener.in/upgrade/ → paste sessionid cookie in .env →
restart dashboard. Everything that depends on this adapter upgrades automatically.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

from src.config import SCREENER_PREMIUM_SESSIONID, SCREENER_SLUG_OVERRIDES, TTL_FUNDAMENTALS
from src.data.base import DataAdapter, fetch_text
from src.data.screener import ScreenerAdapter, _to_float

log = logging.getLogger(__name__)

SCREENER_BASE = "https://www.screener.in"


def is_premium_active() -> bool:
    """Returns True when premium session cookie is set in .env."""
    return bool(SCREENER_PREMIUM_SESSIONID)


def premium_status() -> Dict[str, Any]:
    """Status dict for UI indicator."""
    active = is_premium_active()
    return {
        "active": active,
        "message": (
            "✓ screener.in Premium connected — historical financials + reliable slugs"
            if active else
            "○ screener.in Premium NOT connected — using free tier (10y data still available "
            "but some tickers may 404). Subscribe at screener.in/upgrade/ (₹2,500/yr) and "
            "paste session cookie in .env."
        ),
    }


class ScreenerPremiumAdapter(DataAdapter):
    """Wraps the free adapter, adds historical financials + premium-session HTTP.

    All methods of ScreenerAdapter are inherited. Premium calls fall back to free
    when session not configured."""

    namespace = "screener_premium"
    default_ttl = TTL_FUNDAMENTALS

    def __init__(self):
        super().__init__()
        self._free = ScreenerAdapter()
        # If premium cookie present, layer it into the shared session
        if SCREENER_PREMIUM_SESSIONID:
            self.session.cookies.set("sessionid", SCREENER_PREMIUM_SESSIONID,
                                     domain="screener.in")

    # ============================================================
    # Pass-through for backward compat
    # ============================================================

    def fundamentals(self, ticker: str) -> Dict[str, Any]:
        """When premium active, retry with premium session if free path 404s."""
        result = self._free.fundamentals(ticker)
        if result.get("error") and is_premium_active():
            # Retry with premium session (handles slug redirects)
            try:
                html = self._fetch_company_html(ticker)
                soup = BeautifulSoup(html, "lxml")
                out: Dict[str, Any] = {"ticker": ticker.upper(),
                                       "name": (soup.find("h1").get_text(strip=True)
                                                if soup.find("h1") else None)}
                self._free._parse_top_ratios(soup, out)
                self._free._parse_growth_tables(soup, out)
                de = self._free._compute_de_from_balance_sheet(soup)
                if de is not None:
                    out["debt_to_equity"] = de
                # Sector from compare link
                sector_link = soup.find("a", href=re.compile(r"^/company/compare/"))
                if sector_link:
                    out["sector"] = sector_link.get_text(strip=True)
                return out
            except Exception as exc:
                log.warning("premium retry %s also failed: %s", ticker, exc)
        return result

    def bulk_fundamentals(self, tickers: List[str]) -> pd.DataFrame:
        rows = []
        for t in tickers:
            try:
                rows.append(self.fundamentals(t))
            except Exception as exc:
                log.warning("premium bulk %s: %s", t, exc)
                rows.append({"ticker": t, "error": str(exc)})
        return pd.DataFrame(rows)

    def _fetch_company_html(self, ticker: str, consolidated: bool = True) -> str:
        """Premium-session fetch. Applies slug overrides for known mismatches."""
        slug = SCREENER_SLUG_OVERRIDES.get(ticker.upper(), ticker.upper())
        path = f"/company/{slug}/{'consolidated' if consolidated else ''}/"

        def _load():
            return fetch_text(self.session, SCREENER_BASE + path)

        return self._cached((slug, "prem_html", consolidated), _load)

    # ============================================================
    # NEW: historical financials (premium-only feature, free has limited extraction)
    # ============================================================

    def historical_financials(self, ticker: str) -> Dict[str, pd.DataFrame]:
        """Extract 10y annual P&L + Balance Sheet from company page tables.

        Returns dict with 'pnl' and 'balance_sheet' DataFrames (columns = years,
        rows = line items). Works with free tier too but premium gives more reliable
        slug resolution.
        """
        try:
            html = self._fetch_company_html(ticker, consolidated=True)
        except Exception:
            try:
                html = self._fetch_company_html(ticker, consolidated=False)
            except Exception as exc:
                log.warning("historical_financials fetch %s: %s", ticker, exc)
                return {"pnl": pd.DataFrame(), "balance_sheet": pd.DataFrame()}

        soup = BeautifulSoup(html, "lxml")

        def _parse_section(section_label: str) -> pd.DataFrame:
            for h2 in soup.find_all("h2"):
                if section_label.lower() in h2.get_text(strip=True).lower():
                    tbl = h2.find_next("table")
                    if tbl is None:
                        return pd.DataFrame()
                    rows = []
                    headers = None
                    for tr in tbl.find_all("tr"):
                        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                        if not cells:
                            continue
                        if headers is None:
                            headers = ["metric"] + cells[1:]
                            continue
                        label = cells[0].rstrip("+").strip()
                        values = [_to_float(v) for v in cells[1:]]
                        if label and any(v is not None for v in values):
                            rows.append([label] + values)
                    if rows and headers:
                        df = pd.DataFrame(rows, columns=headers)
                        df = df.set_index("metric")
                        return df
                    return pd.DataFrame()
            return pd.DataFrame()

        return {
            "pnl": _parse_section("Profit & Loss"),
            "balance_sheet": _parse_section("Balance Sheet"),
        }

    def historical_ratios(self, ticker: str) -> pd.DataFrame:
        """Compute year-by-year fundamental ratios from historical financials.

        Returns DataFrame indexed by year-end, columns: revenue, net_profit,
        opm_pct, roe_pct, debt_to_equity, sales_growth_yoy, profit_growth_yoy.
        Removes look-ahead by construction — each row reflects what was knowable
        at that fiscal year-end (plus ~45 days for publication lag in real use)."""
        sec = self.historical_financials(ticker)
        pnl = sec.get("pnl")
        bs = sec.get("balance_sheet")
        if pnl is None or pnl.empty or bs is None or bs.empty:
            return pd.DataFrame()

        # Common metric label resolution (screener.in uses various)
        def _row(df, candidates):
            for c in candidates:
                for idx in df.index:
                    if c.lower() in idx.lower():
                        return df.loc[idx]
            return None

        sales = _row(pnl, ["Sales", "Revenue", "Interest Income"])
        op = _row(pnl, ["Operating Profit"])
        np_ = _row(pnl, ["Net Profit"])
        opm = _row(pnl, ["OPM %"])
        borrow = _row(bs, ["Borrowings"])
        equity = _row(bs, ["Equity Capital"])
        reserves = _row(bs, ["Reserves"])

        if sales is None or np_ is None:
            return pd.DataFrame()

        years = sales.index.tolist()
        rows = []
        for i, y in enumerate(years):
            try:
                rev = float(sales[y]) if pd.notna(sales[y]) else None
                ni = float(np_[y]) if pd.notna(np_[y]) else None
                opmv = float(opm[y]) if opm is not None and pd.notna(opm[y]) else None
                bv = float(borrow[y]) if borrow is not None and pd.notna(borrow[y]) else None
                ev = (float(equity[y]) if equity is not None and pd.notna(equity[y]) else 0) + \
                     (float(reserves[y]) if reserves is not None and pd.notna(reserves[y]) else 0)
                roe = (ni / ev * 100) if ni and ev > 0 else None
                de = (bv / ev) if bv and ev > 0 else None
                # Growth vs PRIOR (earlier-indexed; screener.in tables newest-first)
                prev_y = years[i + 1] if i + 1 < len(years) else None
                if prev_y:
                    prev_rev = float(sales[prev_y]) if pd.notna(sales[prev_y]) else None
                    prev_ni = float(np_[prev_y]) if pd.notna(np_[prev_y]) else None
                    sg = ((rev / prev_rev - 1) * 100) if rev and prev_rev else None
                    pg = ((ni / prev_ni - 1) * 100) if ni and prev_ni and prev_ni != 0 else None
                else:
                    sg = pg = None
                rows.append({
                    "year": y,
                    "revenue_cr": rev,
                    "net_profit_cr": ni,
                    "opm_pct": opmv,
                    "roe_pct": round(roe, 2) if roe is not None else None,
                    "debt_to_equity": round(de, 3) if de is not None else None,
                    "sales_growth_yoy_pct": round(sg, 2) if sg is not None else None,
                    "profit_growth_yoy_pct": round(pg, 2) if pg is not None else None,
                })
            except Exception:
                continue
        df = pd.DataFrame(rows).set_index("year") if rows else pd.DataFrame()
        return df
