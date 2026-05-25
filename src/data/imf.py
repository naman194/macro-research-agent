"""IMF DataMapper API adapter (free, no key required).

Docs: https://www.imf.org/external/datamapper/api/v1
Used for World Economic Outlook indicators across countries.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from src.config import TTL_MACRO
from src.data.base import DataAdapter, fetch_json, make_session

IMF_BASE = "https://www.imf.org/external/datamapper/api/v1"

# IMF blocks browser User-Agents; use plain python-requests UA.
_IMF_HEADERS = {"User-Agent": "python-requests/2.31", "Accept": "application/json"}

# Curated indicator codes from WEO database
IMF_INDICATORS: Dict[str, str] = {
    "GDP_RGROWTH": "NGDP_RPCH",   # Real GDP growth, % YoY
    "INFLATION": "PCPIPCH",       # Inflation, % YoY
    "CURR_ACC_GDP": "BCA_NGDPD",  # Current account % of GDP
    "GG_DEBT_GDP": "GGXWDG_NGDP", # General govt debt % of GDP
    "UNEMP": "LUR",               # Unemployment rate
}

# Countries to surface in the macro view
COUNTRIES = ["IND", "USA", "CHN", "JPN", "DEU", "GBR", "BRA", "RUS", "ZAF", "IDN"]


class IMFAdapter(DataAdapter):
    namespace = "imf"
    default_ttl = TTL_MACRO

    def __init__(self) -> None:
        super().__init__()
        # Override default browser-style headers — IMF DataMapper blocks them.
        self.session = make_session(extra_headers=_IMF_HEADERS)
        # `make_session` re-applies defaults; force-overwrite UA after.
        self.session.headers["User-Agent"] = _IMF_HEADERS["User-Agent"]

    def indicator(self, indicator_code: str, countries: Optional[List[str]] = None) -> pd.DataFrame:
        """Return long-format DataFrame: country, year, value.

        Note: IMF DataMapper ignores the country path filter and returns all 200+ countries;
        we filter client-side. We also include forecast years (IMF WEO is forward-looking).
        """
        countries = countries or COUNTRIES
        # URL still includes countries for cache-key clarity, even though server ignores it.
        url = f"{IMF_BASE}/{indicator_code}"

        def _load():
            return fetch_json(self.session, url)

        data = self._cached((indicator_code, tuple(countries)), _load)
        values = data.get("values", {}).get(indicator_code, {})
        country_set = set(countries)
        rows = []
        for country, by_year in values.items():
            if country not in country_set:
                continue
            for year, val in by_year.items():
                if val is None:
                    continue
                rows.append({"country": country, "year": int(year), "value": float(val)})
        return pd.DataFrame(rows)

    def latest_table(self) -> pd.DataFrame:
        """Wide table: rows = country, cols = indicator label (latest value + projection year)."""
        frames = []
        for label, code in IMF_INDICATORS.items():
            df = self.indicator(code)
            if df.empty:
                continue
            latest = df.sort_values("year").groupby("country").tail(1).copy()
            latest = latest.rename(columns={"value": label, "year": f"{label}_year"})
            frames.append(latest[["country", label, f"{label}_year"]])
        if not frames:
            return pd.DataFrame()
        out = frames[0]
        for f in frames[1:]:
            out = out.merge(f, on="country", how="outer")
        return out.sort_values("country").reset_index(drop=True)
