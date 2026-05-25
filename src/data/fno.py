"""F&O / Open Interest analytics — option chain analysis for indices and stocks.

Uses NSE option-chain-v3 endpoint behind the WAF (handled by nse_session helper).

Compute per-symbol:
  - Put-Call Ratio (PCR by OI) — > 1 = bullish (more puts written), < 1 = bearish
  - Max Pain — strike where total option holders lose the most (gravitational price for expiry)
  - Highest call OI strike = resistance, highest put OI strike = support
  - Total CE / PE OI and change
  - Expiry-specific snapshot

For institutional desk, these are the key tells:
  - PCR < 0.7 → market overly bearish, contrarian long
  - PCR > 1.3 → overly bullish, caution
  - OI buildup at strikes (long buildup, short buildup, etc.) — requires intraday delta
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from src.data.base import DataAdapter
from src.data.nse_session import get_json

log = logging.getLogger(__name__)


# F&O underlying universe (most actively traded)
DEFAULT_FNO_INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
DEFAULT_FNO_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
    "SBIN", "AXISBANK", "ITC", "LT", "KOTAKBANK",
    "MARUTI", "TATAMOTORS", "BAJFINANCE", "BHARTIARTL",
]


class FnoAdapter(DataAdapter):
    namespace = "fno"
    default_ttl = 15 * 60  # 15 min — option chain is highly time-sensitive

    @staticmethod
    def _is_index(symbol: str) -> bool:
        return symbol.upper() in {"NIFTY", "BANKNIFTY", "FINNIFTY", "NIFTYIT", "MIDCPNIFTY"}

    def option_chain(self, symbol: str, expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Raw option chain for symbol + optional expiry. v3 endpoint REQUIRES a real expiry;
        if none given, we discover the list with a placeholder call then re-fetch."""
        sym = symbol.upper()
        api_type = "Indices" if self._is_index(sym) else "Equity"
        path = "/api/option-chain-v3"

        def _resolve_expiry() -> Optional[str]:
            # First call with a placeholder to discover available expiries
            discovery = get_json(path, params={"type": api_type, "symbol": sym,
                                               "expiry": "01-Jan-2099"})
            if not discovery:
                return None
            exps = (discovery.get("records") or {}).get("expiryDates") or []
            return exps[0] if exps else None

        def _load():
            resolved = expiry or _resolve_expiry()
            if not resolved:
                return None
            data = get_json(path, params={"type": api_type, "symbol": sym, "expiry": resolved})
            return data

        return self._cached((sym, expiry or "nearest"), _load)

    def analytics(self, symbol: str, expiry: Optional[str] = None) -> Dict[str, Any]:
        """Compute PCR, max pain, support/resistance from option chain."""
        sym = symbol.upper()
        chain = self.option_chain(sym, expiry)
        if not chain or "records" not in chain:
            return {"symbol": sym, "error": "no option chain data"}

        records = chain["records"]
        data = records.get("data", []) or []
        underlying = records.get("underlyingValue", 0)
        expiry_dates = records.get("expiryDates", []) or []

        # If no expiry was passed, default to nearest; the API often returns the full chain.
        if not expiry:
            expiry = expiry_dates[0] if expiry_dates else None

        # Server already filters by expiry; no need to re-filter (date formats differ:
        # URL uses "26-May-2026", response uses "26-05-2026" — would mismatch).
        rows: List[Dict[str, Any]] = []
        for d in data:
            strike = d.get("strikePrice")
            ce = d.get("CE") or {}
            pe = d.get("PE") or {}
            rows.append({
                "strike": strike,
                "ce_oi": ce.get("openInterest") or 0,
                "ce_chg_oi": ce.get("changeinOpenInterest") or 0,
                "ce_volume": ce.get("totalTradedVolume") or 0,
                "ce_iv": ce.get("impliedVolatility") or 0,
                "ce_ltp": ce.get("lastPrice") or 0,
                "pe_oi": pe.get("openInterest") or 0,
                "pe_chg_oi": pe.get("changeinOpenInterest") or 0,
                "pe_volume": pe.get("totalTradedVolume") or 0,
                "pe_iv": pe.get("impliedVolatility") or 0,
                "pe_ltp": pe.get("lastPrice") or 0,
            })

        if not rows:
            return {"symbol": sym, "underlying": underlying, "expiry": expiry,
                    "error": "no rows for expiry"}

        df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)

        total_ce_oi = int(df["ce_oi"].sum())
        total_pe_oi = int(df["pe_oi"].sum())
        total_ce_chg = int(df["ce_chg_oi"].sum())
        total_pe_chg = int(df["pe_chg_oi"].sum())
        pcr_oi = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi else None
        pcr_chg = round(total_pe_chg / total_ce_chg, 3) if total_ce_chg else None

        # Support / resistance — strikes with max OI
        max_ce = df.loc[df["ce_oi"].idxmax()] if df["ce_oi"].max() > 0 else None
        max_pe = df.loc[df["pe_oi"].idxmax()] if df["pe_oi"].max() > 0 else None

        # Max pain: strike at which total premium paid out (= cash settled value to OTM
        # holders) is minimized for the OPTION WRITER, equivalently the strike where the
        # SUM of intrinsic value across all open contracts is minimized.
        def _pain_at_strike(K: float) -> float:
            ce_pain = ((df["strike"] - K).clip(lower=0) * df["ce_oi"]).sum()  # writer loses on ITM CE
            pe_pain = ((K - df["strike"]).clip(lower=0) * df["pe_oi"]).sum()  # writer loses on ITM PE
            return float(ce_pain + pe_pain)
        df["max_pain_score"] = df["strike"].apply(_pain_at_strike)
        max_pain_strike = float(df.loc[df["max_pain_score"].idxmin(), "strike"])

        # Sentiment label
        sentiment = "neutral"
        if pcr_oi is not None:
            if pcr_oi >= 1.3: sentiment = "bullish (PCR >= 1.3 — heavy put writing)"
            elif pcr_oi >= 1.0: sentiment = "mildly bullish"
            elif pcr_oi >= 0.7: sentiment = "mildly bearish"
            else: sentiment = "bearish (PCR < 0.7 — heavy call writing)"

        return {
            "symbol": sym,
            "expiry": expiry,
            "available_expiries": expiry_dates[:6],
            "underlying": float(underlying) if underlying else None,
            "pcr_oi": pcr_oi,
            "pcr_chg_oi": pcr_chg,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "total_ce_chg_oi": total_ce_chg,
            "total_pe_chg_oi": total_pe_chg,
            "max_pain_strike": max_pain_strike,
            "max_pain_distance_pct": (round((max_pain_strike / underlying - 1) * 100, 2)
                                      if underlying else None),
            "resistance_strike": float(max_ce["strike"]) if max_ce is not None else None,
            "resistance_oi": int(max_ce["ce_oi"]) if max_ce is not None else 0,
            "support_strike": float(max_pe["strike"]) if max_pe is not None else None,
            "support_oi": int(max_pe["pe_oi"]) if max_pe is not None else 0,
            "sentiment": sentiment,
        }

    def chain_table(self, symbol: str, expiry: Optional[str] = None,
                    strikes_around: int = 10) -> pd.DataFrame:
        """Option chain centered on ATM, ±N strikes (for the UI table)."""
        sym = symbol.upper()
        chain = self.option_chain(sym, expiry)
        if not chain or "records" not in chain:
            return pd.DataFrame()
        records = chain["records"]
        data = records.get("data", []) or []
        underlying = records.get("underlyingValue", 0)
        expiry_dates = records.get("expiryDates", []) or []
        if not expiry:
            expiry = expiry_dates[0] if expiry_dates else None

        rows = []
        for d in data:
            strike = d.get("strikePrice")
            ce = d.get("CE") or {}
            pe = d.get("PE") or {}
            rows.append({
                "strike": strike,
                "CE OI": ce.get("openInterest") or 0,
                "CE ΔOI": ce.get("changeinOpenInterest") or 0,
                "CE IV": ce.get("impliedVolatility") or 0,
                "CE LTP": ce.get("lastPrice") or 0,
                "PE LTP": pe.get("lastPrice") or 0,
                "PE IV": pe.get("impliedVolatility") or 0,
                "PE ΔOI": pe.get("changeinOpenInterest") or 0,
                "PE OI": pe.get("openInterest") or 0,
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)
        if underlying:
            # Trim to ±N strikes around ATM
            atm_idx = (df["strike"] - underlying).abs().idxmin()
            lo = max(0, atm_idx - strikes_around)
            hi = min(len(df), atm_idx + strikes_around + 1)
            df = df.iloc[lo:hi].reset_index(drop=True)
        return df

    def headline_signals(self) -> List[Dict[str, Any]]:
        """Compact summary for morning brief: PCR + max-pain + S/R for indices."""
        out = []
        for sym in DEFAULT_FNO_INDICES:
            try:
                a = self.analytics(sym)
                if "error" in a:
                    continue
                out.append({
                    "symbol": sym, "underlying": a.get("underlying"),
                    "expiry": a.get("expiry"), "pcr_oi": a.get("pcr_oi"),
                    "sentiment": a.get("sentiment"),
                    "max_pain": a.get("max_pain_strike"),
                    "max_pain_distance_pct": a.get("max_pain_distance_pct"),
                    "resistance": a.get("resistance_strike"),
                    "support": a.get("support_strike"),
                })
            except Exception as exc:
                log.warning("F&O headline for %s failed: %s", sym, exc)
        return out
