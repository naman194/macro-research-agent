"""NSE adapter — corporate events & live quotes via nsepython.

nsepython handles NSE's cookie/header dance reasonably well. We wrap it so the rest of
the codebase doesn't depend on the library directly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pandas as pd

from src.config import TTL_FILINGS, TTL_QUOTES
from src.data.base import DataAdapter

log = logging.getLogger(__name__)


class NSEAdapter(DataAdapter):
    namespace = "nse"
    default_ttl = TTL_QUOTES

    def __init__(self) -> None:
        super().__init__()
        self._nsepython = None
        try:
            import nsepython
            self._nsepython = nsepython
        except Exception as exc:
            log.warning("nsepython import failed; NSE adapter limited: %s", exc)

    @property
    def available(self) -> bool:
        return self._nsepython is not None

    def quote(self, ticker: str) -> Dict[str, Any]:
        if not self.available:
            return {"ticker": ticker, "error": "nsepython unavailable"}

        def _load():
            try:
                q = self._nsepython.nse_eq(ticker.upper())
            except Exception as exc:
                return {"ticker": ticker.upper(), "error": f"nse_eq failed: {exc}"}
            if not isinstance(q, dict) or not q:
                # NSE is blocking — common; we still return a shaped payload so UI doesn't break.
                return {"ticker": ticker.upper(),
                        "error": "NSE returned empty (throttled). Price/52w via screener.in instead."}
            info = q.get("info", {}) or {}
            price = q.get("priceInfo", {}) or {}
            return {
                "ticker": ticker.upper(),
                "company": info.get("companyName"),
                "isin": info.get("isin"),
                "last_price": price.get("lastPrice"),
                "day_change": price.get("change"),
                "day_change_pct": price.get("pChange"),
                "high_52w": (price.get("weekHighLow") or {}).get("max"),
                "low_52w": (price.get("weekHighLow") or {}).get("min"),
                "vwap": price.get("vwap"),
                "as_of": datetime.utcnow().isoformat(),
            }

        return self._cached((ticker.upper(),), _load, ttl=TTL_QUOTES)

    def announcements(self, ticker: str, lookback_days: int = 90) -> List[Dict[str, Any]]:
        """Upcoming and recent corporate events (board meetings, results, dividends) for ticker.

        Uses nsepython.nse_events() which returns the consolidated NSE corporate-events
        feed; we filter to this symbol.
        """
        if not self.available:
            return []

        def _load():
            df = self._nsepython.nse_events()
            if not isinstance(df, pd.DataFrame) or df.empty:
                return []
            sym = ticker.upper()
            filtered = df[df["symbol"].str.upper() == sym].copy()
            if filtered.empty:
                return []
            cutoff = datetime.utcnow() - timedelta(days=lookback_days)
            out = []
            for _, row in filtered.iterrows():
                date_str = row.get("date", "")
                try:
                    dt = datetime.strptime(str(date_str), "%d-%b-%Y")
                except Exception:
                    dt = datetime.utcnow()
                if dt < cutoff and dt > datetime.utcnow() - timedelta(days=lookback_days * 2):
                    continue
                out.append({
                    "ticker": sym,
                    "subject": str(row.get("purpose") or ""),
                    "details": str(row.get("bm_desc") or ""),
                    "date": dt.date().isoformat(),
                })
            out.sort(key=lambda x: x["date"], reverse=True)
            return out

        return self._cached((ticker.upper(), lookback_days), _load, ttl=TTL_FILINGS)
