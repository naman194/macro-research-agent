"""GARP — Growth at a Reasonable Price (Lynch / Lipper style).

Hard filters:
  - PEG <= 1.5  (P/E divided by 3y profit growth %)
  - 3y profit growth >= 12% (real growth, well above India CPI)
  - 3y sales growth  >= 10%
  - ROE >= 12% (lower bar than Q+V; growth firms can have lower returns on equity)
  - D/E <= 1.0 (more lenient than Q+V)
  - Market cap >= INR 1,000 Cr

Composite score (0-100):
  - Growth quality 40%: profit growth 3y (25%) + earnings acceleration (TTM vs 3y, 15%)
  - Reasonable price 30%: inverse PEG (20%) + inverse P/E vs sector median (10%)
  - Operating quality 20%: ROCE (12%) + ROE (8%)
  - Momentum 10%: 1y price CAGR positive bonus
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from src.config import TICKER_SECTOR_MAP
from src.data.catalysts import catalyst_breakdown, company_catalysts
from src.data.screener import ScreenerAdapter
from src.data.structural_risks import for_company, for_sector, penalty_breakdown
from src.screens.base import Screener, ScreenResult


MIN_MCAP_CR = 1000
MAX_PEG = 1.5
MIN_PROFIT_GROWTH_3Y = 12.0
MIN_SALES_GROWTH_3Y = 10.0
MIN_ROE = 12.0
MAX_DE = 1.0


def _norm(v: Optional[float], lo: float, hi: float) -> float:
    if v is None:
        return 0.0
    v = max(min(v, hi), lo)
    return (v - lo) / (hi - lo) * 100.0


def _peg(pe: Optional[float], growth_pct: Optional[float]) -> Optional[float]:
    if pe is None or growth_pct is None or growth_pct <= 0:
        return None
    return round(pe / growth_pct, 2)


class GARPScreener(Screener):
    framework = "garp"

    def __init__(self, adapter: ScreenerAdapter = None):
        self.adapter = adapter or ScreenerAdapter()

    def run(self, universe: List[str]) -> ScreenResult:
        raw = self.adapter.bulk_fundamentals(universe)
        if raw.empty:
            return ScreenResult(framework=self.framework, candidates=pd.DataFrame(),
                                notes=["No fundamentals returned"], criteria=self._criteria())

        # Ensure expected columns exist
        for col in ["market_cap_cr", "roce", "roe", "debt_to_equity", "pe",
                    "sales_growth_3y", "profit_growth_3y", "profit_growth_ttm",
                    "price_cagr_1y", "sector", "name"]:
            if col not in raw.columns:
                raw[col] = None

        # Compute PEG inline
        raw["peg"] = raw.apply(
            lambda r: _peg(self._safe(r, "pe"), self._safe(r, "profit_growth_3y")), axis=1
        )

        # Hard filters
        mask = (
            (raw["market_cap_cr"].apply(lambda x: self._safe_cmp(x, MIN_MCAP_CR, "ge")))
            & (raw["peg"].apply(lambda x: x is not None and 0 < x <= MAX_PEG))
            & (raw["profit_growth_3y"].apply(lambda x: self._safe_cmp(x, MIN_PROFIT_GROWTH_3Y, "ge")))
            & (raw["sales_growth_3y"].apply(lambda x: self._safe_cmp(x, MIN_SALES_GROWTH_3Y, "ge")))
            & (raw["roe"].apply(lambda x: self._safe_cmp(x, MIN_ROE, "ge")))
            & (raw["debt_to_equity"].apply(lambda x: self._safe_cmp(x, MAX_DE, "le", default_pass=True)))
        )
        passed = raw[mask].copy()
        rejected = int(len(raw) - len(passed))

        # Sector-median P/E for the relative-value component
        sector_pe_median = passed.groupby("sector")["pe"].median().to_dict()

        scores = []
        for _, row in passed.iterrows():
            pe = self._safe(row, "pe") or 100
            peg_v = row.get("peg")
            pg3 = self._safe(row, "profit_growth_3y") or 0
            pg_ttm = self._safe(row, "profit_growth_ttm") or pg3
            sg3 = self._safe(row, "sales_growth_3y") or 0
            roce = self._safe(row, "roce") or 0
            roe = self._safe(row, "roe") or 0
            price_cagr_1y = self._safe(row, "price_cagr_1y") or 0
            sector = row.get("sector") or TICKER_SECTOR_MAP.get(row["ticker"].upper())
            sect_med_pe = sector_pe_median.get(sector)

            acceleration = max(pg_ttm - pg3, 0)  # only reward positive acceleration
            growth_q = _norm(pg3, 12, 40) * 0.25 + _norm(acceleration, 0, 20) * 0.15

            inv_peg = _norm(1.0 / max(peg_v or 99, 0.1), 0.5, 2.0) * 0.20
            rel_pe = 0.0
            if sect_med_pe and sect_med_pe > 0 and pe > 0:
                premium = (pe / sect_med_pe) - 1  # negative if cheaper than peers
                rel_pe = _norm(-premium, -0.5, 0.5) * 0.10
            reasonable_price = inv_peg + rel_pe

            op_q = _norm(roce, 12, 35) * 0.12 + _norm(roe, 12, 30) * 0.08

            mom = _norm(price_cagr_1y, -10, 40) * 0.10

            raw_score = round(growth_q + reasonable_price + op_q + mom, 2)
            ticker = row["ticker"]
            penalty = penalty_breakdown(sector=sector, ticker=ticker)
            bonus = catalyst_breakdown(sector=sector, ticker=ticker)
            company_risks = for_company(ticker).get("risks") or []
            company_cats = company_catalysts(ticker).get("catalysts") or []
            adjusted_score = round(max(
                raw_score - penalty["total_penalty"] + bonus["total_catalyst_bonus"], 0), 2)
            scores.append({
                "ticker": ticker,
                "name": row.get("name"),
                "sector": sector,
                "score": adjusted_score,
                "raw_score": raw_score,
                "sector_penalty": penalty["sector_penalty"],
                "company_penalty": penalty["company_penalty"],
                "structural_penalty": penalty["total_penalty"],
                "sector_catalyst": bonus["sector_catalyst_bonus"],
                "company_catalyst": bonus["company_catalyst_bonus"],
                "catalyst_bonus": bonus["total_catalyst_bonus"],
                "net_overlay": round(bonus["total_catalyst_bonus"] - penalty["total_penalty"], 2),
                "company_flags": ", ".join(r["risk"] for r in company_risks) or None,
                "company_catalysts": ", ".join(c["catalyst"] for c in company_cats) or None,
                "structural_label": for_sector(sector).get("label", ""),
                "peg": peg_v,
                "growth_sub": round(growth_q, 2),
                "price_sub": round(reasonable_price, 2),
                "quality_sub": round(op_q, 2),
                "momentum_sub": round(mom, 2),
                "pe": pe,
                "profit_growth_3y": pg3,
                "profit_growth_ttm": pg_ttm,
                "sales_growth_3y": sg3,
                "roce": roce,
                "roe": roe,
                "debt_to_equity": self._safe(row, "debt_to_equity"),
                "market_cap_cr": self._safe(row, "market_cap_cr"),
                "price_cagr_1y": price_cagr_1y,
            })

        candidates = pd.DataFrame(scores).sort_values("score", ascending=False).reset_index(drop=True)
        return ScreenResult(
            framework=self.framework,
            candidates=candidates,
            rejected_count=rejected,
            criteria=self._criteria(),
            notes=[f"Screened {len(raw)} names; {len(candidates)} passed hard filters."],
        )

    @staticmethod
    def _safe_cmp(value, threshold, op: str, default_pass: bool = False) -> bool:
        """Compare value to threshold safely; missing data fails unless default_pass=True."""
        try:
            v = float(value)
            if pd.isna(v):
                return default_pass
        except (TypeError, ValueError):
            return default_pass
        if op == "ge":
            return v >= threshold
        if op == "le":
            return v <= threshold
        if op == "gt":
            return v > threshold
        if op == "lt":
            return v < threshold
        return False

    def _criteria(self):
        return {
            "min_market_cap_cr": f">= {MIN_MCAP_CR}",
            "max_peg": f"<= {MAX_PEG}",
            "min_3y_profit_growth_pct": f">= {MIN_PROFIT_GROWTH_3Y}",
            "min_3y_sales_growth_pct": f">= {MIN_SALES_GROWTH_3Y}",
            "min_roe_pct": f">= {MIN_ROE}",
            "max_debt_to_equity": f"<= {MAX_DE}",
            "scoring": "Growth 40% / Reasonable Price 30% / Quality 20% / Momentum 10%",
        }
