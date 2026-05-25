"""Block & Bulk deals adapter — daily institutional prints from NSE archives.

Uses NSE archives CSV (`nsearchives.nseindia.com/content/equities/{bulk,block}.csv`)
which is the publicly-published daily snapshot — no auth, no JS challenge.

Bulk deals = transactions >= 0.5% of company's listed shares on a single day.
Block deals = transactions >= 5 lakh shares or Rs 5 crore value executed in the
              block trading window (different settlement, often more institutional).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from src.data.base import DataAdapter
from src.data.nse_session import session

log = logging.getLogger(__name__)

BULK_CSV = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
BLOCK_CSV = "https://nsearchives.nseindia.com/content/equities/block.csv"


# Counterparty name patterns that mark institutional flow.
# Used to flag rows for the morning brief.
INSTITUTIONAL_PATTERNS = [
    "MUTUAL FUND", " MF ", " AMC ",
    "INSURANCE", "LIC ", " LIFE INSURANCE",
    "FII", "FPI", "FOREIGN PORTFOLIO",
    "PENSION FUND", "EPFO",
    "ALTERNATIVE INVESTMENT FUND", " AIF ",
    "PORTFOLIO MANAGEMENT", " PMS ",
    "ASSET MANAGEMENT", "INVESTMENT FUND",
    "SOVEREIGN", "BHARTI WEALTH", "ICICI PRUDENTIAL",
    "NIPPON LIFE", "AXIS MUTUAL", "HDFC AMC",
    "KOTAK MAHINDRA", "SBI MUTUAL", "EDELWEISS",
    "MIRAE ASSET", "MORGAN STANLEY", "GOLDMAN SACHS",
    "VANGUARD", "BLACKROCK", "FIDELITY", "T. ROWE PRICE",
    "ABU DHABI", "GOVERNMENT OF SINGAPORE",
]


def _is_institutional(client_name: str) -> bool:
    upper = (client_name or "").upper()
    return any(pat in upper for pat in INSTITUTIONAL_PATTERNS)


class DealsAdapter(DataAdapter):
    namespace = "deals"
    default_ttl = 6 * 3600  # refresh ~6h

    def _fetch_csv(self, url: str) -> pd.DataFrame:
        def _load():
            try:
                s = session()
                r = s.get(url, timeout=20)
                r.raise_for_status()
                return r.text
            except Exception as exc:
                log.warning("deals fetch %s failed: %s", url, exc)
                return ""

        text = self._cached((url,), _load)
        if not text:
            return pd.DataFrame()
        try:
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        except Exception as exc:
            log.warning("CSV parse failed: %s", exc)
            return pd.DataFrame()
        if not rows:
            return pd.DataFrame()
        return self._normalize(pd.DataFrame(rows))

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        # Trim/rename columns; NSE CSV has whitespace in headers
        df = df.rename(columns={c: c.strip() for c in df.columns})
        cmap = {
            "Date": "date", "Symbol": "symbol", "Security Name": "security",
            "Client Name": "client", "Buy/Sell": "side",
            "Quantity Traded": "qty",
            "Trade Price / Wght. Avg. Price": "price",
            "Remarks": "remarks",
        }
        df = df.rename(columns={k: v for k, v in cmap.items() if k in df.columns})
        for c in ("qty", "price"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
        if "qty" in df.columns and "price" in df.columns:
            df["value_cr"] = (df["qty"] * df["price"] / 1e7).round(2)
        if "client" in df.columns:
            df["institutional"] = df["client"].apply(_is_institutional)
        return df

    def bulk_deals(self) -> pd.DataFrame:
        return self._fetch_csv(BULK_CSV)

    def block_deals(self) -> pd.DataFrame:
        return self._fetch_csv(BLOCK_CSV)

    def latest_summary(self, top_n: int = 15) -> Dict[str, Any]:
        """Compact summary for morning brief: top deals by value, big institutional buys."""
        bulk = self.bulk_deals()
        block = self.block_deals()

        def _top(df: pd.DataFrame, n: int, side: Optional[str] = None) -> List[Dict[str, Any]]:
            if df.empty:
                return []
            d = df.copy()
            if side:
                d = d[d["side"].str.upper() == side]
            d = d.dropna(subset=["value_cr"]).sort_values("value_cr", ascending=False).head(n)
            return d.to_dict("records")

        return {
            "latest_date": (bulk["date"].iloc[0] if not bulk.empty and "date" in bulk.columns
                            else block["date"].iloc[0] if not block.empty else None),
            "bulk_top_buys": _top(bulk, top_n, side="BUY"),
            "bulk_top_sells": _top(bulk, top_n, side="SELL"),
            "block_top": _top(block, top_n),
            "institutional_buys": _top(bulk[bulk.get("institutional", False)] if not bulk.empty else bulk, top_n, side="BUY"),
            "bulk_count": len(bulk),
            "block_count": len(block),
        }
