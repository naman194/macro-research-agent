"""screener.in adapter — fundamentals for Indian listed companies.

No official API. We scrape the rendered company page; the structure is stable enough
for our use. Heavily cached because fundamentals only change on results day.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from bs4 import BeautifulSoup

from src.config import SCREENER_SLUG_OVERRIDES, TTL_FUNDAMENTALS
from src.data.base import DataAdapter, fetch_text

log = logging.getLogger(__name__)

SCREENER_BASE = "https://www.screener.in"


def _to_float(text: str) -> Optional[float]:
    if text is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(text).replace(",", ""))
    if not cleaned or cleaned in {"-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


class ScreenerAdapter(DataAdapter):
    namespace = "screener"
    default_ttl = TTL_FUNDAMENTALS

    def _fetch_company_html(self, ticker: str, consolidated: bool = True) -> str:
        slug = SCREENER_SLUG_OVERRIDES.get(ticker.upper(), ticker.upper())
        path = f"/company/{slug}/{'consolidated' if consolidated else ''}/"

        def _load():
            return fetch_text(self.session, SCREENER_BASE + path)

        return self._cached((slug, "html", consolidated), _load)

    def fundamentals(self, ticker: str) -> Dict[str, Any]:
        """Return key fundamentals scraped from screener.in company page."""
        try:
            html = self._fetch_company_html(ticker, consolidated=True)
        except Exception:
            try:
                html = self._fetch_company_html(ticker, consolidated=False)
            except Exception as exc:
                log.warning("screener fetch failed for %s: %s", ticker, exc)
                return {"ticker": ticker.upper(), "error": str(exc)}

        soup = BeautifulSoup(html, "lxml")
        out: Dict[str, Any] = {"ticker": ticker.upper()}

        # Company name
        h1 = soup.find("h1")
        if h1:
            out["name"] = h1.get_text(strip=True)

        # Sector (first compare link points to industry peers)
        sector_link = soup.find("a", href=re.compile(r"^/company/compare/"))
        if sector_link:
            out["sector"] = sector_link.get_text(strip=True)

        # Top ratios panel (spans)
        self._parse_top_ratios(soup, out)

        # Compounded growth + ROE history tables
        self._parse_growth_tables(soup, out)

        # Debt-to-equity computed from balance sheet
        de = self._compute_de_from_balance_sheet(soup)
        if de is not None:
            out["debt_to_equity"] = de

        return out

    # -------- helpers --------

    def _parse_top_ratios(self, soup: BeautifulSoup, out: Dict[str, Any]) -> None:
        ratio_map = {
            "Market Cap": "market_cap_cr",
            "Current Price": "current_price",
            "Stock P/E": "pe",
            "Book Value": "book_value",
            "Dividend Yield": "dividend_yield",
            "ROCE": "roce",
            "ROE": "roe",
            "Face Value": "face_value",
            "Price to book value": "price_to_book",
        }
        for li in soup.select("ul#top-ratios li"):
            name_el = li.find("span", class_="name")
            value_el = li.find("span", class_="value")
            if not name_el or not value_el:
                continue
            label = name_el.get_text(strip=True)
            key = ratio_map.get(label)
            if not key:
                continue
            raw = value_el.get_text(" ", strip=True)
            out[key] = _to_float(raw)

    def _parse_growth_tables(self, soup: BeautifulSoup, out: Dict[str, Any]) -> None:
        """Parses Compounded Sales Growth, Compounded Profit Growth, Stock Price CAGR,
        Return on Equity tables — small 4-row tables with periods 10y/5y/3y/TTM."""
        for tbl in soup.find_all("table"):
            rows = tbl.find_all("tr")
            if not rows or len(rows) < 2:
                continue
            head_cell = rows[0].find(["td", "th"])
            if not head_cell:
                continue
            head = head_cell.get_text(strip=True)

            key_for_period = self._growth_key_for_header(head)
            if key_for_period is None:
                continue

            for r in rows[1:]:
                cells = r.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                period_label = cells[0].get_text(" ", strip=True)
                value = _to_float(cells[-1].get_text(" ", strip=True))
                period = self._parse_period_label(period_label)
                if period is None:
                    continue
                out[key_for_period(period)] = value

    @staticmethod
    def _growth_key_for_header(header: str):
        h = header.lower()
        if "compounded sales growth" in h:
            return lambda p: f"sales_growth_{p}"
        if "compounded profit growth" in h:
            return lambda p: f"profit_growth_{p}"
        if "stock price cagr" in h:
            return lambda p: f"price_cagr_{p}"
        if "return on equity" in h:
            return lambda p: f"roe_{p}"
        return None

    @staticmethod
    def _parse_period_label(label: str) -> Optional[str]:
        l = label.lower()
        if "10 year" in l:
            return "10y"
        if "5 year" in l:
            return "5y"
        if "3 year" in l:
            return "3y"
        if "ttm" in l or "last year" in l or "1 year" in l:
            return "ttm" if "ttm" in l else "1y"
        return None

    def _compute_de_from_balance_sheet(self, soup: BeautifulSoup) -> Optional[float]:
        """Find Balance Sheet table; D/E = Borrowings / (Equity Capital + Reserves), latest col."""
        for h2 in soup.find_all(["h2"]):
            if "balance sheet" not in h2.get_text(strip=True).lower():
                continue
            tbl = h2.find_next("table")
            if not tbl:
                continue
            borrowings = None
            equity = None
            reserves = None
            for r in tbl.find_all("tr"):
                cells = r.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(" ", strip=True).lower().rstrip("+").strip()
                latest = _to_float(cells[-1].get_text(" ", strip=True))
                if "borrowings" in label and borrowings is None:
                    borrowings = latest
                elif "equity capital" in label:
                    equity = latest
                elif "reserves" in label:
                    reserves = latest
            denom = (equity or 0) + (reserves or 0)
            if borrowings is None or denom <= 0:
                return None
            return round(borrowings / denom, 3)
        return None

    def bulk_fundamentals(self, tickers: List[str]) -> pd.DataFrame:
        rows = []
        for t in tickers:
            try:
                rows.append(self.fundamentals(t))
            except Exception as exc:
                log.warning("bulk fundamentals %s failed: %s", t, exc)
                rows.append({"ticker": t, "error": str(exc)})
        return pd.DataFrame(rows)

    # -------- quarterly results + shareholding (Phase P0) --------

    def quarterly_results(self, ticker: str) -> Dict[str, Any]:
        """Parse the Quarterly Results section. Returns dict with metric rows + computed
        YoY/QoQ for revenue, EBITDA, margins, EPS."""
        try:
            html = self._fetch_company_html(ticker, consolidated=True)
        except Exception:
            try:
                html = self._fetch_company_html(ticker, consolidated=False)
            except Exception as exc:
                return {"ticker": ticker.upper(), "error": str(exc)}

        soup = BeautifulSoup(html, "lxml")
        section = self._find_section_table(soup, "Quarterly Results")
        if not section:
            return {"ticker": ticker.upper(), "error": "Quarterly Results section not found"}

        periods, metrics = self._parse_period_table(section)
        if not periods:
            return {"ticker": ticker.upper(), "error": "Could not parse quarterly periods"}

        # Compute changes for key metrics
        result: Dict[str, Any] = {"ticker": ticker.upper(), "periods": periods, "metrics": metrics}
        for key, label in [("Sales", "revenue"), ("Operating Profit", "ebitda"),
                           ("Net Profit", "net_profit"), ("OPM %", "opm_pct"),
                           ("EPS in Rs", "eps")]:
            row = metrics.get(key)
            if not row or len(row) < 5:
                continue
            latest = row[-1]; prev_q = row[-2] if len(row) > 1 else None
            yoy_idx = -5 if len(row) >= 5 else None
            yoy_q = row[yoy_idx] if yoy_idx is not None else None
            result[label] = {
                "latest_value": latest, "latest_period": periods[-1],
                "qoq_pct": _pct_change(latest, prev_q),
                "yoy_pct": _pct_change(latest, yoy_q),
                "prev_quarter": prev_q, "yoy_quarter": yoy_q,
            }
        return result

    def shareholding(self, ticker: str) -> Dict[str, Any]:
        """Parse Shareholding Pattern: promoter / FII / DII / govt / public over time."""
        try:
            html = self._fetch_company_html(ticker, consolidated=True)
        except Exception:
            try:
                html = self._fetch_company_html(ticker, consolidated=False)
            except Exception as exc:
                return {"ticker": ticker.upper(), "error": str(exc)}

        soup = BeautifulSoup(html, "lxml")
        section = self._find_section_table(soup, "Shareholding Pattern")
        if not section:
            return {"ticker": ticker.upper(), "error": "Shareholding section not found"}

        periods, metrics = self._parse_period_table(section)
        if not periods:
            return {"ticker": ticker.upper(), "error": "Could not parse shareholding periods"}

        out: Dict[str, Any] = {"ticker": ticker.upper(), "periods": periods,
                               "holders": metrics}
        # Compute QoQ delta for the key holders
        for key in ["Promoters", "FIIs", "DIIs", "Government", "Public"]:
            row = metrics.get(key)
            if not row or len(row) < 2:
                continue
            latest = row[-1]; prev = row[-2]
            if latest is not None and prev is not None:
                out[f"{key.lower()}_qoq_change"] = round(latest - prev, 2)
                out[f"{key.lower()}_latest"] = latest
        return out

    @staticmethod
    def _find_section_table(soup: BeautifulSoup, heading_text: str):
        for h2 in soup.find_all(["h2", "h3"]):
            if heading_text.lower() in h2.get_text(strip=True).lower():
                return h2.find_next("table")
        return None

    @staticmethod
    def _parse_period_table(tbl) -> tuple:
        """Generic parser for screener.in's wide tables (period columns, metric rows)."""
        rows = tbl.find_all("tr")
        if not rows:
            return [], {}
        # Header row → periods
        header_cells = [c.get_text(" ", strip=True) for c in rows[0].find_all(["td", "th"])]
        # First cell is empty / "" so periods are header_cells[1:]
        periods = [c for c in header_cells[1:] if c]
        metrics: Dict[str, List[Optional[float]]] = {}
        for r in rows[1:]:
            cells = r.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(" ", strip=True).rstrip("+").strip()
            if not label:
                continue
            values = [_to_float(c.get_text(" ", strip=True)) for c in cells[1:]]
            metrics[label] = values
        return periods, metrics


def _pct_change(latest, prior) -> Optional[float]:
    if latest is None or prior is None or prior == 0:
        return None
    try:
        return round(((latest - prior) / abs(prior)) * 100, 2)
    except (TypeError, ZeroDivisionError):
        return None
