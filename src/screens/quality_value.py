"""Quality + Value screener (Buffett/Munger flavour).

Hard filters:
  - ROCE >= 15%
  - ROE >= 15%
  - D/E <= 0.5
  - 3y sales growth > 0 and 3y profit growth > 0
  - Market cap >= INR 1,000 Cr

Soft scoring (0-100 composite) — higher is better:
  - Quality:  ROCE (30%)  + ROE (20%)  + low D/E (10%)
  - Value:    inverse P/E (15%) + dividend yield (5%)
  - Growth:   3y profit CAGR (15%) + 3y sales CAGR (5%)

Rejected names are returned in the result for transparency.
"""
from __future__ import annotations

from typing import List

import pandas as pd

from src.config import TICKER_SECTOR_MAP
from src.data.catalysts import catalyst_breakdown, company_catalysts
from src.data.screener import ScreenerAdapter
from src.data.structural_risks import for_company, for_sector, penalty_breakdown
from src.screens.base import Screener, ScreenResult


MIN_MCAP_CR = 1000
MIN_ROCE = 15.0
MIN_ROE = 15.0
MAX_DE = 0.5


def _norm(v, lo, hi):
    if v is None:
        return 0.0
    v = max(min(v, hi), lo)
    return (v - lo) / (hi - lo) * 100.0


class QualityValueScreener(Screener):
    framework = "quality_value"

    def __init__(self, adapter: ScreenerAdapter = None):
        self.adapter = adapter or ScreenerAdapter()

    def run(self, universe: List[str]) -> ScreenResult:
        raw = self.adapter.bulk_fundamentals(universe)
        if raw.empty:
            return ScreenResult(framework=self.framework, candidates=pd.DataFrame(),
                                notes=["No fundamentals returned"], criteria=self._criteria())

        # Ensure all expected columns exist
        for col in ["market_cap_cr", "roce", "roe", "debt_to_equity", "pe",
                    "dividend_yield", "sales_growth_3y", "profit_growth_3y",
                    "sector", "name"]:
            if col not in raw.columns:
                raw[col] = None

        passed_mask = (
            (raw["market_cap_cr"].astype(float, errors="ignore") >= MIN_MCAP_CR)
            & (raw["roce"].astype(float, errors="ignore") >= MIN_ROCE)
            & (raw["roe"].astype(float, errors="ignore") >= MIN_ROE)
            & (raw["debt_to_equity"].astype(float, errors="ignore") <= MAX_DE)
            & (raw["sales_growth_3y"].astype(float, errors="ignore") > 0)
            & (raw["profit_growth_3y"].astype(float, errors="ignore") > 0)
        )
        passed_mask = passed_mask.fillna(False)
        passed = raw[passed_mask].copy()
        rejected_count = int(len(raw) - len(passed))

        scores = []
        for _, row in passed.iterrows():
            roce = self._safe(row, "roce") or 0
            roe = self._safe(row, "roe") or 0
            de = self._safe(row, "debt_to_equity") or 1.0
            pe = self._safe(row, "pe") or 100.0
            dy = self._safe(row, "dividend_yield") or 0
            sg = self._safe(row, "sales_growth_3y") or 0
            pg = self._safe(row, "profit_growth_3y") or 0

            quality = _norm(roce, 15, 40) * 0.30 + _norm(roe, 15, 35) * 0.20 + \
                      _norm(1.0 - min(de, 1.0), 0.5, 1.0) * 0.10
            value = _norm(1.0 / max(pe, 1), 0.02, 0.08) * 0.15 + _norm(dy, 0, 5) * 0.05
            growth = _norm(pg, 0, 30) * 0.15 + _norm(sg, 0, 25) * 0.05

            raw_score = round(quality + value + growth, 2)
            ticker = row["ticker"]
            sector = row.get("sector") or TICKER_SECTOR_MAP.get(ticker.upper())
            penalty = penalty_breakdown(sector=sector, ticker=ticker)
            bonus = catalyst_breakdown(sector=sector, ticker=ticker)
            company_risks = for_company(ticker).get("risks") or []
            company_cats = company_catalysts(ticker).get("catalysts") or []
            adjusted_score = round(max(
                raw_score - penalty["total_penalty"] + bonus["total_catalyst_bonus"],
                0), 2)
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
                "quality_sub": round(quality, 2),
                "value_sub": round(value, 2),
                "growth_sub": round(growth, 2),
                "roce": roce,
                "roe": roe,
                "debt_to_equity": de,
                "pe": pe,
                "dividend_yield": dy,
                "market_cap_cr": self._safe(row, "market_cap_cr"),
                "sales_growth_3y": sg,
                "profit_growth_3y": pg,
            })

        candidates = pd.DataFrame(scores).sort_values("score", ascending=False).reset_index(drop=True)
        return ScreenResult(
            framework=self.framework,
            candidates=candidates,
            rejected_count=rejected_count,
            criteria=self._criteria(),
            notes=[f"Screened {len(raw)} names; {len(candidates)} passed hard filters."]
        )

    def _criteria(self):
        return {
            "min_market_cap_cr": f">= {MIN_MCAP_CR}",
            "min_roce_pct": f">= {MIN_ROCE}",
            "min_roe_pct": f">= {MIN_ROE}",
            "max_debt_to_equity": f"<= {MAX_DE}",
            "min_3y_sales_growth": "> 0",
            "min_3y_profit_growth": "> 0",
            "scoring": "Quality 60% / Value 20% / Growth 20% — minus structural-risk penalty (sector 0-30 + company 0-15)",
            "structural_overlay": "Two-layer overlay: sector-level (IT/GenAI, Banks/NIM, Pharma/USFDA etc.) + company-level (TCS/BFSI concentration, HDFCBANK/post-merger drag, MARUTI/EV roadmap etc.). Total deducted from raw score. See `raw_score`, `sector_penalty`, `company_penalty`, `company_flags` columns.",
        }
