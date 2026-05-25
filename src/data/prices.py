"""yfinance-based OHLCV adapter for NSE stocks + indices + global cues.

Covers:
  - Indian indices: NIFTY 50, BANKNIFTY, SENSEX, sectoral indices (IT, Pharma, Auto, Metal, FMCG, Energy)
  - Global cues: S&P 500, Nasdaq, Nikkei, Hang Seng, FTSE, gold, WTI, Brent, INR=X, US 10Y
  - Universe stocks via "{TICKER}.NS" suffix
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from src.data.base import DataAdapter

log = logging.getLogger(__name__)


INDIAN_INDICES: Dict[str, str] = {
    "Nifty 50": "^NSEI",
    "Bank Nifty": "^NSEBANK",
    "Sensex": "^BSESN",
    "Nifty IT": "^CNXIT",
    "Nifty Pharma": "^CNXPHARMA",
    "Nifty Auto": "^CNXAUTO",
    "Nifty Metal": "^CNXMETAL",
    "Nifty FMCG": "^CNXFMCG",
    "Nifty Energy": "^CNXENERGY",
    "Nifty Realty": "^CNXREALTY",
}

GLOBAL_CUES: Dict[str, str] = {
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "Dow Jones": "^DJI",
    "Nikkei 225": "^N225",
    "Hang Seng": "^HSI",
    "FTSE 100": "^FTSE",
    "Gold ($/oz)": "GC=F",
    "WTI Crude ($/bbl)": "CL=F",
    "Brent ($/bbl)": "BZ=F",
    "USD/INR": "INR=X",
    "US 10Y": "^TNX",
    "VIX": "^VIX",
}


class PricesAdapter(DataAdapter):
    """All methods are cached in-process per Python session (yfinance has its own
    on-disk session via curl_cffi; SQLite caching adds little for daily OHLCV)."""

    namespace = "prices"
    default_ttl = 30 * 60  # 30 min — intraday refresh during trading hours

    def __init__(self) -> None:
        super().__init__()
        try:
            import yfinance as yf
            self._yf = yf
        except Exception as exc:
            log.warning("yfinance import failed: %s", exc)
            self._yf = None

    @property
    def available(self) -> bool:
        return self._yf is not None

    # ---- core OHLCV ----

    def history(self, symbol: str, period: str = "300d", interval: str = "1d") -> pd.DataFrame:
        if not self.available:
            return pd.DataFrame()
        try:
            df = self._yf.Ticker(symbol).history(period=period, interval=interval)
            if df.empty:
                return df
            df = df.tz_localize(None) if df.index.tz is not None else df
            return df
        except Exception as exc:
            log.warning("yfinance history %s failed: %s", symbol, exc)
            return pd.DataFrame()

    def latest(self, symbol: str) -> Optional[Dict]:
        """Last close + % chg from prior close."""
        df = self.history(symbol, period="10d")
        if df.empty or len(df) < 2:
            return None
        last = df.iloc[-1]
        prev = df.iloc[-2]
        return {
            "symbol": symbol,
            "as_of": df.index[-1].date().isoformat(),
            "close": float(last["Close"]),
            "open": float(last["Open"]),
            "high": float(last["High"]),
            "low": float(last["Low"]),
            "volume": int(last.get("Volume") or 0),
            "prev_close": float(prev["Close"]),
            "change": float(last["Close"] - prev["Close"]),
            "change_pct": float((last["Close"] / prev["Close"] - 1) * 100),
        }

    # ---- summary tables ----

    def indices_snapshot(self) -> pd.DataFrame:
        rows = []
        for name, sym in INDIAN_INDICES.items():
            q = self.latest(sym)
            if not q:
                continue
            rows.append({"index": name, "symbol": sym, **{k: v for k, v in q.items() if k not in ("symbol",)}})
        return pd.DataFrame(rows)

    def global_cues_snapshot(self) -> pd.DataFrame:
        rows = []
        for name, sym in GLOBAL_CUES.items():
            q = self.latest(sym)
            if not q:
                continue
            rows.append({"cue": name, "symbol": sym, **{k: v for k, v in q.items() if k not in ("symbol",)}})
        return pd.DataFrame(rows)

    def universe_ohlcv(self, tickers: List[str], period: str = "300d") -> Dict[str, pd.DataFrame]:
        """Bulk pull. yfinance handles batching internally."""
        if not self.available or not tickers:
            return {}
        symbols = [f"{t.upper()}.NS" for t in tickers]
        try:
            data = self._yf.download(
                tickers=" ".join(symbols),
                period=period, interval="1d",
                group_by="ticker", auto_adjust=True,
                threads=True, progress=False,
            )
        except Exception as exc:
            log.warning("yfinance bulk download failed: %s", exc)
            return {}
        out: Dict[str, pd.DataFrame] = {}
        if isinstance(data.columns, pd.MultiIndex):
            for sym in symbols:
                try:
                    sub = data[sym].dropna(how="all")
                    if not sub.empty:
                        out[sym.replace(".NS", "")] = sub
                except KeyError:
                    pass
        else:
            # Single ticker case
            if symbols and not data.empty:
                out[symbols[0].replace(".NS", "")] = data
        return out

    def market_breadth_and_movers(self, tickers: List[str]) -> Dict:
        """From universe OHLCV: advance/decline ratio + top gainers/losers (1d)."""
        bulk = self.universe_ohlcv(tickers, period="10d")
        if not bulk:
            return {"advances": 0, "declines": 0, "unchanged": 0,
                    "gainers": [], "losers": []}
        moves = []
        for tkr, df in bulk.items():
            if df.empty or len(df) < 2 or "Close" not in df.columns:
                continue
            last = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])
            if prev <= 0:
                continue
            pct = (last / prev - 1) * 100
            moves.append({
                "ticker": tkr, "close": round(last, 2),
                "prev_close": round(prev, 2),
                "change_pct": round(pct, 2),
                "volume": int(df["Volume"].iloc[-1]) if "Volume" in df.columns else 0,
            })
        if not moves:
            return {"advances": 0, "declines": 0, "unchanged": 0,
                    "gainers": [], "losers": []}
        df = pd.DataFrame(moves)
        advances = int((df["change_pct"] > 0).sum())
        declines = int((df["change_pct"] < 0).sum())
        unchanged = int((df["change_pct"] == 0).sum())
        gainers = df.nlargest(7, "change_pct").to_dict("records")
        losers = df.nsmallest(7, "change_pct").to_dict("records")
        return {
            "advances": advances, "declines": declines, "unchanged": unchanged,
            "adv_dec_ratio": round(advances / max(declines, 1), 2),
            "gainers": gainers, "losers": losers,
        }
