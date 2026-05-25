"""World Bank API adapter (free, no key required).

Docs: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392
Used for cross-country structural indicators and policy rates.
"""
from __future__ import annotations

from typing import Dict, List

import pandas as pd

from src.config import TTL_MACRO
from src.data.base import DataAdapter, fetch_json

WB_BASE = "https://api.worldbank.org/v2"

WB_INDICATORS: Dict[str, str] = {
    "GDP_GROWTH": "NY.GDP.MKTP.KD.ZG",         # Real GDP growth %
    "INFLATION": "FP.CPI.TOTL.ZG",             # CPI inflation %
    "POLICY_RATE": "FR.INR.LEND",              # Lending rate %
    "REAL_RATE": "FR.INR.RINR",                # Real interest rate %
    "FX_RESERVES_USD": "FI.RES.TOTL.CD",       # FX reserves (USD)
    "GROSS_SAVINGS_GDP": "NY.GNS.ICTR.ZS",     # Gross savings % GDP
    "GROSS_CAPITAL_GDP": "NE.GDI.TOTL.ZS",     # Gross capital formation % GDP
}

COUNTRIES_ISO2 = ["IN", "US", "CN", "JP", "DE", "GB", "BR", "RU", "ZA", "ID"]


class WorldBankAdapter(DataAdapter):
    namespace = "worldbank"
    default_ttl = TTL_MACRO

    def indicator(self, code: str, countries: List[str] = None) -> pd.DataFrame:
        """Long-format: country, year, value (last 10y)."""
        countries = countries or COUNTRIES_ISO2
        country_str = ";".join(countries)
        url = f"{WB_BASE}/country/{country_str}/indicator/{code}"
        params = {"format": "json", "per_page": "2000", "date": "2015:2026"}

        def _load():
            data = fetch_json(self.session, url, params=params)
            # Response is [meta, [observations...]]
            if not isinstance(data, list) or len(data) < 2:
                return []
            return data[1] or []

        obs = self._cached((code, tuple(countries)), _load)
        rows = []
        for o in obs:
            if o.get("value") is None:
                continue
            rows.append({
                "country": o["country"]["id"],
                "country_name": o["country"]["value"],
                "year": int(o["date"]),
                "value": float(o["value"]),
            })
        return pd.DataFrame(rows)

    def latest_table(self) -> pd.DataFrame:
        frames = []
        for label, code in WB_INDICATORS.items():
            df = self.indicator(code)
            if df.empty:
                continue
            latest = df.sort_values("year").groupby("country").tail(1).copy()
            latest = latest.rename(columns={"value": label, "year": f"{label}_year"})
            frames.append(latest[["country", "country_name", label, f"{label}_year"]])
        if not frames:
            return pd.DataFrame()
        out = frames[0]
        for f in frames[1:]:
            out = out.merge(f, on=["country", "country_name"], how="outer")
        return out.sort_values("country").reset_index(drop=True)
