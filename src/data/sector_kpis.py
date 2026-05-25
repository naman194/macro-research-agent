"""Sector-specific KPI extractors.

Each sector has different things institutional desks watch. We pull from the same
screener.in quarterly P&L + balance sheet that the core adapter already scrapes,
then extract sector-specific lines (NIM for banks, attrition mentions for IT, etc.).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import pandas as pd
from bs4 import BeautifulSoup

from src.data.base import DataAdapter
from src.data.prices import PricesAdapter
from src.data.screener import ScreenerAdapter, _to_float
from src.config import TTL_FUNDAMENTALS

log = logging.getLogger(__name__)


# Curated coverage universe per sector
BANK_UNIVERSE = ["HDFCBANK", "ICICIBANK", "AXISBANK", "SBIN", "KOTAKBANK",
                 "INDUSINDBK", "IDFCFIRSTB", "FEDERALBNK", "BANDHANBNK", "AUBANK"]
IT_UNIVERSE = ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "MPHASIS",
               "COFORGE", "PERSISTENT", "LTTS"]
AUTO_UNIVERSE = ["MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO", "HEROMOTOCO",
                 "EICHERMOT", "TVSMOTOR", "ASHOKLEY", "BOSCHLTD", "MOTHERSON"]


# ---- Bank KPIs ----

def _bank_kpis(screener: ScreenerAdapter, ticker: str) -> Dict[str, Any]:
    """Extract bank-specific KPIs from screener.in quarterly P&L."""
    q = screener.quarterly_results(ticker)
    if "error" in q:
        return {"ticker": ticker, "error": q["error"]}
    metrics = q.get("metrics", {})
    periods = q.get("periods", [])
    if not periods:
        return {"ticker": ticker, "error": "no periods"}

    def _latest(key: str) -> Optional[float]:
        row = metrics.get(key)
        return row[-1] if row else None

    def _pct_chg(key: str, periods_back: int) -> Optional[float]:
        row = metrics.get(key)
        if not row or len(row) <= periods_back:
            return None
        latest = row[-1]; prior = row[-1 - periods_back]
        if latest is None or prior is None or prior == 0:
            return None
        return round(((latest - prior) / abs(prior)) * 100, 2)

    revenue = _latest("Revenue") or _latest("Interest Income") or _latest("Sales")
    net_profit = _latest("Net Profit")
    operating_profit = _latest("Operating Profit")
    fundamentals = screener.fundamentals(ticker)

    return {
        "ticker": ticker.upper(),
        "name": fundamentals.get("name"),
        "latest_period": periods[-1] if periods else None,
        "revenue_cr": revenue,
        "revenue_yoy_pct": _pct_chg("Revenue", 4) or _pct_chg("Interest Income", 4) or _pct_chg("Sales", 4),
        "revenue_qoq_pct": _pct_chg("Revenue", 1) or _pct_chg("Interest Income", 1) or _pct_chg("Sales", 1),
        "net_profit_cr": net_profit,
        "net_profit_yoy_pct": _pct_chg("Net Profit", 4),
        "net_profit_qoq_pct": _pct_chg("Net Profit", 1),
        "operating_profit_cr": operating_profit,
        "opm_pct": _latest("OPM %"),
        "financing_profit": _latest("Financing Profit"),
        "financing_margin_pct": _latest("Financing Margin %"),
        "roe_pct": fundamentals.get("roe"),
        "roa_pct": None,  # not directly on screener
        "price": fundamentals.get("current_price"),
        "pe": fundamentals.get("pe"),
        "price_to_book": fundamentals.get("price_to_book"),
        "market_cap_cr": fundamentals.get("market_cap_cr"),
    }


# ---- IT KPIs ----

def _it_kpis(screener: ScreenerAdapter, prices: PricesAdapter, ticker: str) -> Dict[str, Any]:
    q = screener.quarterly_results(ticker)
    if "error" in q:
        return {"ticker": ticker, "error": q["error"]}
    metrics = q.get("metrics", {})
    periods = q.get("periods", [])

    def _latest(key: str): r = metrics.get(key); return r[-1] if r else None
    def _pct(key, n):
        r = metrics.get(key)
        if not r or len(r) <= n: return None
        l, p = r[-1], r[-1-n]
        if l is None or p is None or p == 0: return None
        return round(((l-p)/abs(p))*100, 2)

    fundamentals = screener.fundamentals(ticker)

    # USDINR sensitivity: 90-day correlation of stock returns vs USDINR
    usdinr_sens = None
    try:
        stock = prices.history(f"{ticker}.NS", period="120d")
        inr = prices.history("INR=X", period="120d")
        if not stock.empty and not inr.empty and len(stock) > 30 and len(inr) > 30:
            sr = stock["Close"].pct_change().dropna()
            ir = inr["Close"].pct_change().dropna()
            # Align on dates
            combined = pd.concat([sr.rename("stock"), ir.rename("inr")], axis=1).dropna()
            if len(combined) > 30:
                usdinr_sens = round(combined["stock"].corr(combined["inr"]), 3)
    except Exception:
        pass

    return {
        "ticker": ticker.upper(),
        "name": fundamentals.get("name"),
        "latest_period": periods[-1] if periods else None,
        "revenue_cr": _latest("Sales") or _latest("Revenue"),
        "revenue_yoy_pct": _pct("Sales", 4) or _pct("Revenue", 4),
        "revenue_qoq_pct": _pct("Sales", 1) or _pct("Revenue", 1),
        "opm_pct": _latest("OPM %"),
        "opm_yoy_change_pp": (_latest("OPM %") - metrics.get("OPM %", [None])[-5]
                              if metrics.get("OPM %") and len(metrics["OPM %"]) > 4
                              and metrics["OPM %"][-1] is not None
                              and metrics["OPM %"][-5] is not None else None),
        "net_profit_cr": _latest("Net Profit"),
        "net_profit_yoy_pct": _pct("Net Profit", 4),
        "usdinr_correlation_90d": usdinr_sens,
        "roce": fundamentals.get("roce"),
        "roe": fundamentals.get("roe"),
        "pe": fundamentals.get("pe"),
        "dividend_yield": fundamentals.get("dividend_yield"),
        "market_cap_cr": fundamentals.get("market_cap_cr"),
    }


# ---- Auto KPIs ----

def _auto_kpis(screener: ScreenerAdapter, ticker: str) -> Dict[str, Any]:
    q = screener.quarterly_results(ticker)
    if "error" in q:
        return {"ticker": ticker, "error": q["error"]}
    metrics = q.get("metrics", {})
    periods = q.get("periods", [])

    def _latest(key: str): r = metrics.get(key); return r[-1] if r else None
    def _pct(key, n):
        r = metrics.get(key)
        if not r or len(r) <= n: return None
        l, p = r[-1], r[-1-n]
        if l is None or p is None or p == 0: return None
        return round(((l-p)/abs(p))*100, 2)

    fundamentals = screener.fundamentals(ticker)

    return {
        "ticker": ticker.upper(),
        "name": fundamentals.get("name"),
        "latest_period": periods[-1] if periods else None,
        "revenue_cr": _latest("Sales") or _latest("Revenue"),
        "revenue_yoy_pct": _pct("Sales", 4) or _pct("Revenue", 4),
        "revenue_qoq_pct": _pct("Sales", 1) or _pct("Revenue", 1),
        "opm_pct": _latest("OPM %"),
        "opm_yoy_change_pp": (_latest("OPM %") - metrics.get("OPM %", [None])[-5]
                              if metrics.get("OPM %") and len(metrics["OPM %"]) > 4
                              and metrics["OPM %"][-1] is not None
                              and metrics["OPM %"][-5] is not None else None),
        "net_profit_cr": _latest("Net Profit"),
        "net_profit_yoy_pct": _pct("Net Profit", 4),
        "roce": fundamentals.get("roce"),
        "roe": fundamentals.get("roe"),
        "pe": fundamentals.get("pe"),
        "price": fundamentals.get("current_price"),
        "market_cap_cr": fundamentals.get("market_cap_cr"),
        "debt_to_equity": fundamentals.get("debt_to_equity"),
    }


class SectorAdapter(DataAdapter):
    namespace = "sector"
    default_ttl = TTL_FUNDAMENTALS

    def __init__(self):
        super().__init__()
        self.screener = ScreenerAdapter()
        self.prices = PricesAdapter()

    def banks(self, tickers: List[str] = None) -> pd.DataFrame:
        tickers = tickers or BANK_UNIVERSE
        rows = []
        for t in tickers:
            try:
                rows.append(_bank_kpis(self.screener, t))
            except Exception as exc:
                log.warning("banks %s: %s", t, exc)
                rows.append({"ticker": t, "error": str(exc)})
        return pd.DataFrame(rows)

    def it(self, tickers: List[str] = None) -> pd.DataFrame:
        tickers = tickers or IT_UNIVERSE
        rows = []
        for t in tickers:
            try:
                rows.append(_it_kpis(self.screener, self.prices, t))
            except Exception as exc:
                log.warning("it %s: %s", t, exc)
                rows.append({"ticker": t, "error": str(exc)})
        return pd.DataFrame(rows)

    def auto(self, tickers: List[str] = None) -> pd.DataFrame:
        tickers = tickers or AUTO_UNIVERSE
        rows = []
        for t in tickers:
            try:
                rows.append(_auto_kpis(self.screener, t))
            except Exception as exc:
                log.warning("auto %s: %s", t, exc)
                rows.append({"ticker": t, "error": str(exc)})
        return pd.DataFrame(rows)
