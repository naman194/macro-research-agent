"""FII / DII daily cash market flows from NSE.

The endpoint /api/fiidiiTradeReact is public, no cookie warmup needed, returns clean JSON.
Cached 6h — figures publish once daily after close.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

import requests

from src.data.base import DataAdapter

log = logging.getLogger(__name__)

NSE_FII_DII = "https://www.nseindia.com/api/fiidiiTradeReact"


class FlowsAdapter(DataAdapter):
    namespace = "flows"
    default_ttl = 6 * 3600

    def fii_dii_latest(self) -> List[Dict[str, Any]]:
        """Latest day's FII + DII cash-market flows (buy/sell/net in Rs Cr)."""
        def _load():
            try:
                r = requests.get(
                    NSE_FII_DII,
                    headers={"User-Agent": "Mozilla/5.0",
                             "Accept": "application/json"},
                    timeout=15,
                )
                r.raise_for_status()
                data = r.json()
            except Exception as exc:
                log.warning("NSE FII/DII fetch failed: %s", exc)
                return []
            out = []
            for row in data or []:
                try:
                    out.append({
                        "date": row.get("date"),
                        "category": row.get("category"),
                        "buy_cr": float(row.get("buyValue") or 0),
                        "sell_cr": float(row.get("sellValue") or 0),
                        "net_cr": float(row.get("netValue") or 0),
                    })
                except Exception:
                    continue
            return out

        return self._cached(("fii_dii_latest",), _load)

    def fii_dii_summary_line(self) -> str:
        """One-line text summary for inclusion in morning brief."""
        rows = self.fii_dii_latest()
        if not rows:
            return "FII/DII: data unavailable today."
        date = rows[0].get("date", "")
        parts = [f"FII/DII ({date}):"]
        for r in rows:
            cat = r["category"]
            net = r["net_cr"]
            sign = "+" if net >= 0 else ""
            parts.append(f"{cat} net {sign}{net:,.0f} Cr (buy {r['buy_cr']:,.0f} / sell {r['sell_cr']:,.0f})")
        return " · ".join(parts)
