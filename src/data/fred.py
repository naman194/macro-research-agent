"""FRED adapter — US Fed economic data via fredapi.

Used for US benchmark rates, CPI, GDP, yield curve (drives risk-on/risk-off macro tilt
for emerging markets including India).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from src.config import FRED_API_KEY, TTL_MACRO
from src.data.base import DataAdapter

# Curated FRED series that drive India-relevant macro
FRED_SERIES: Dict[str, str] = {
    "US_FEDFUNDS": "FEDFUNDS",          # US Fed Funds rate
    "US_CPI_YOY": "CPIAUCSL",           # US CPI (we compute YoY)
    "US_10Y": "DGS10",                  # US 10Y treasury
    "US_2Y": "DGS2",                    # US 2Y treasury
    "US_GDP_GROWTH": "A191RL1Q225SBEA", # US real GDP growth (annualized %)
    "US_UNEMP": "UNRATE",               # US unemployment
    "DXY": "DTWEXBGS",                  # Broad USD index
    "WTI_OIL": "DCOILWTICO",            # WTI crude
    "VIX": "VIXCLS",                    # CBOE VIX
}


class FredAdapter(DataAdapter):
    namespace = "fred"
    default_ttl = TTL_MACRO

    def __init__(self) -> None:
        super().__init__()
        self._client = None
        if FRED_API_KEY:
            try:
                from fredapi import Fred
                self._client = Fred(api_key=FRED_API_KEY)
            except Exception:
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def series(self, code: str, start: str = "2015-01-01") -> pd.Series:
        """Fetch a raw FRED series by code."""
        if not self.available:
            return pd.Series(dtype=float, name=code)

        def _load() -> List:
            s = self._client.get_series(code, observation_start=start)
            s.index = pd.to_datetime(s.index)
            return [[d.isoformat(), float(v) if pd.notna(v) else None] for d, v in s.items()]

        records = self._cached((code, start), _load)
        if not records:
            return pd.Series(dtype=float, name=code)
        idx = pd.to_datetime([r[0] for r in records])
        vals = [r[1] for r in records]
        return pd.Series(vals, index=idx, name=code, dtype=float)

    def snapshot(self) -> pd.DataFrame:
        """Return a wide-format DataFrame of the latest value for each curated series,
        plus 1m / 3m / 12m change."""
        rows = []
        for label, code in FRED_SERIES.items():
            s = self.series(code).dropna()
            if s.empty:
                rows.append({"indicator": label, "code": code, "latest": None,
                             "change_1m": None, "change_3m": None, "change_12m": None,
                             "as_of": None})
                continue
            latest = float(s.iloc[-1])
            as_of = s.index[-1].date().isoformat()

            def _chg(periods_days: int) -> Optional[float]:
                cutoff = s.index[-1] - pd.Timedelta(days=periods_days)
                prior = s[s.index <= cutoff]
                if prior.empty:
                    return None
                return float(latest - prior.iloc[-1])

            rows.append({
                "indicator": label,
                "code": code,
                "latest": latest,
                "change_1m": _chg(30),
                "change_3m": _chg(90),
                "change_12m": _chg(365),
                "as_of": as_of,
            })
        df = pd.DataFrame(rows)

        # CPI -> YoY %
        cpi_idx = df["indicator"] == "US_CPI_YOY"
        if cpi_idx.any():
            cpi_series = self.series("CPIAUCSL").dropna()
            if not cpi_series.empty and len(cpi_series) > 12:
                latest_v = cpi_series.iloc[-1]
                prior_v = cpi_series.iloc[-13]
                yoy = (latest_v / prior_v - 1) * 100
                df.loc[cpi_idx, "latest"] = round(yoy, 2)

        return df
