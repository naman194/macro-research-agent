"""Insider & Promoter trading disclosures (SEBI PIT regulations).

NSE publishes PIT (Prohibition of Insider Trading) disclosures at
/api/corporates-pit. Returns all insider/promoter buy and sell transactions with
acquirer name, role, security count, transaction value.

Promoter buys = high-conviction internal signal (rare, illegal if not disclosed).
ESOP sells = noise (every CEO does it for liquidity / tax).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from src.data.base import DataAdapter
from src.data.nse_session import get_json

log = logging.getLogger(__name__)


PROMOTER_HINTS = ["PROMOTER", "PROMOTERS"]
ESOP_HINTS = ["ESOP", "STOCK OPTION", "EMPLOYEE STOCK"]


def _is_promoter(role: str) -> bool:
    return any(h in (role or "").upper() for h in PROMOTER_HINTS)


def _is_esop(mode: str) -> bool:
    return any(h in (mode or "").upper() for h in ESOP_HINTS)


def _to_float(v) -> Optional[float]:
    try:
        if v in (None, "", "-"):
            return None
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


class InsiderAdapter(DataAdapter):
    namespace = "insider"
    default_ttl = 6 * 3600

    def transactions(self, days_back: int = 30) -> pd.DataFrame:
        """All PIT disclosures filed in the last `days_back` days. Default 30d to
        ensure useful volume (NSE has filing delays and quiet weeks)."""
        today = date.today()
        from_date = (today - timedelta(days=days_back)).strftime("%d-%m-%Y")
        to_date = today.strftime("%d-%m-%Y")

        def _load():
            params = {"index": "equities", "from_date": from_date, "to_date": to_date}
            data = get_json("/api/corporates-pit", params=params)
            if not data:
                return []
            return data.get("data") or []

        rows = self._cached((from_date, to_date), _load)
        if not rows:
            return pd.DataFrame()

        out = []
        for r in rows:
            # Authoritative transaction type from the disclosure form
            txn_type = (r.get("tdpTransactionType") or "").strip()
            qty = _to_float(r.get("secAcq")) or 0
            buy_val = _to_float(r.get("buyValue")) or 0
            sell_val = _to_float(r.get("sellValue")) or 0

            # Normalize side using both signals
            side = "OTHER"
            if "buy" in txn_type.lower():
                side = "BUY"
            elif "sell" in txn_type.lower():
                side = "SELL"
            elif "pledge revoke" in txn_type.lower():
                side = "PLEDGE_REVOKE"
            elif "pledge invoke" in txn_type.lower():
                side = "PLEDGE_INVOKE"
            elif "pledge" in txn_type.lower():
                side = "PLEDGE"
            elif buy_val > sell_val:
                side = "BUY"
            elif sell_val > 0:
                side = "SELL"

            out.append({
                "date": (r.get("date") or "")[:11],
                "symbol": r.get("symbol"),
                "company": r.get("company"),
                "acq_name": r.get("acqName"),
                "role": r.get("personCategory") or r.get("acquirerType") or "",
                "mode": r.get("acquisitionMode") or "",
                "txn_type": txn_type or side,
                "side": side,
                "qty": int(qty) if qty else 0,
                "buy_value_cr": round(buy_val / 1e7, 3) if buy_val else 0,
                "sell_value_cr": round(sell_val / 1e7, 3) if sell_val else 0,
                "anex": r.get("anex"),
            })
        df = pd.DataFrame(out)
        df["is_promoter"] = df["role"].apply(_is_promoter)
        df["is_esop"] = df["mode"].apply(_is_esop)
        return df

    def latest_summary(self, days_back: int = 30, top_n: int = 15) -> Dict[str, Any]:
        df = self.transactions(days_back=days_back)
        if df.empty:
            return {"total": 0, "promoter_buys": [], "promoter_sells": [],
                    "other_buys": [], "other_sells": [], "pledges": [], "as_of": None}

        # Drop ESOP for highlight lists — noise (every CEO does these for liquidity)
        signal = df[~df["is_esop"]].copy()
        proms = signal[signal["is_promoter"]]
        others = signal[~signal["is_promoter"]]
        buys = signal[signal["side"] == "BUY"]
        sells = signal[signal["side"] == "SELL"]
        pledges = signal[signal["side"].isin(["PLEDGE", "PLEDGE_REVOKE", "PLEDGE_INVOKE"])]

        def _top(d: pd.DataFrame, by: str, n: int) -> List[Dict]:
            if d.empty:
                return []
            # If value column has data, sort by it; else sort by qty
            sortable = d[d[by] > 0] if by in d.columns and (d[by] > 0).any() else d
            sort_col = by if not sortable.empty and (sortable[by] > 0).any() else "qty"
            return sortable.sort_values(sort_col, ascending=False).head(n).to_dict("records")

        return {
            "total": int(len(df)),
            "as_of": df["date"].max() if "date" in df.columns and not df.empty else None,
            "promoter_buys": _top(proms[proms["side"] == "BUY"], "buy_value_cr", top_n),
            "promoter_sells": _top(proms[proms["side"] == "SELL"], "sell_value_cr", top_n),
            "other_buys": _top(others[others["side"] == "BUY"], "buy_value_cr", top_n),
            "other_sells": _top(others[others["side"] == "SELL"], "sell_value_cr", top_n),
            "pledges": pledges.head(top_n).to_dict("records"),
        }
