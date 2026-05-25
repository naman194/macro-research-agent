"""Index rebalance predictor — likely Nifty 50 / Next 50 add/drop candidates.

NSE Indices rebalances semi-annually (Jan + Jul cutoff dates). The methodology:
  - Eligibility: F&O-listed, sufficient turnover, free-float market cap rank
  - Replacement triggered when a current member drops below rank ~70 (for Nifty 50)
    AND a non-member ranks above ~30

This module:
  1. Pulls current Nifty 50 + Next 50 constituent lists (hardcoded — they change rarely)
  2. Ranks the broader Nifty 500 universe by full market cap
  3. Identifies likely additions (high-ranking non-members in Nifty 50)
  4. Identifies likely deletions (Nifty 50 members ranking outside top 70)
  5. Estimates passive flow if rebalance happens

Caveat: NSE uses *free-float* mcap with specific multipliers. We approximate using
full mcap from screener.in. Results are directionally correct, exact ranks may differ.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import pandas as pd

from src.data.base import DataAdapter
from src.data.screener import ScreenerAdapter
from src.config import TTL_FUNDAMENTALS

log = logging.getLogger(__name__)


# As-of late 2025 / early 2026 — refresh these lists semi-annually
NIFTY_50_CONSTITUENTS = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BHARTIARTL", "BPCL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
    "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT",
    "LTIM", "M&M", "MARUTI", "NESTLEIND", "NTPC",
    "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN",
    "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL",
    "TCS", "TECHM", "TITAN", "ULTRACEMCO", "WIPRO",
]

# Approximate Nifty Next 50 (top adds to N50 typically come from here)
NIFTY_NEXT_50 = [
    "ABB", "ADANIGREEN", "ADANIPOWER", "AMBUJACEM", "BAJAJHLDNG",
    "BANKBARODA", "BERGEPAINT", "BOSCHLTD", "CANBK", "CHOLAFIN",
    "COLPAL", "DABUR", "DLF", "DMART", "GAIL",
    "GODREJCP", "HAVELLS", "HAL", "ICICIGI", "ICICIPRULI",
    "IOC", "INDIGO", "IRFC", "JINDALSTEL", "JIOFIN",
    "LICI", "LODHA", "MARICO", "NHPC", "NAUKRI",
    "PFC", "PIDILITIND", "PNB", "RECLTD", "SBICARD",
    "SHREECEM", "SIEMENS", "TATAPOWER", "TORNTPHARM", "TVSMOTOR",
    "TRENT", "UNITDSPR", "VBL", "VEDL", "ZOMATO",
    "ZYDUSLIFE", "ATGL", "CGPOWER", "MUTHOOTFIN", "MOTHERSON",
]


# Approximate Nifty 50 passive AUM (Indian ETFs + index funds)
# Rs ~3.5 lakh Cr tracks Nifty 50 actively (as of 2025) — used to estimate passive flows
NIFTY_50_PASSIVE_AUM_CR = 350_000


class IndexRebalanceAdapter(DataAdapter):
    namespace = "rebalance"
    default_ttl = TTL_FUNDAMENTALS

    def __init__(self):
        super().__init__()
        self.screener = ScreenerAdapter()

    def universe_with_mcaps(self, tickers: List[str]) -> pd.DataFrame:
        """Pull market cap for each ticker via cached fundamentals."""
        rows = []
        for t in tickers:
            try:
                f = self.screener.fundamentals(t)
                rows.append({
                    "ticker": t,
                    "name": f.get("name"),
                    "market_cap_cr": f.get("market_cap_cr"),
                    "current_price": f.get("current_price"),
                    "pe": f.get("pe"),
                })
            except Exception as exc:
                log.warning("rebalance fund pull %s failed: %s", t, exc)
        return pd.DataFrame(rows).dropna(subset=["market_cap_cr"])

    def predict_nifty50_changes(self) -> Dict[str, Any]:
        """Combine N50 + Next 50 universe, rank by mcap, identify likely add/drop."""
        universe = sorted(set(NIFTY_50_CONSTITUENTS + NIFTY_NEXT_50))
        df = self.universe_with_mcaps(universe)
        if df.empty:
            return {"error": "Could not pull market caps"}
        df = df.sort_values("market_cap_cr", ascending=False).reset_index(drop=True)
        df["rank"] = df.index + 1
        df["in_nifty50"] = df["ticker"].isin(NIFTY_50_CONSTITUENTS)

        # Likely deletions: current N50 members ranked > 55 (below safe zone)
        likely_deletions = df[(df["in_nifty50"]) & (df["rank"] > 55)].copy()
        # Likely additions: non-N50 ranked <= 50 (in safe zone)
        likely_additions = df[(~df["in_nifty50"]) & (df["rank"] <= 50)].copy()

        # Passive flow estimate for adds (roughly proportional to their weight in N50)
        n50_total_mcap = df[df["in_nifty50"]]["market_cap_cr"].sum()
        likely_additions["est_weight_pct"] = (likely_additions["market_cap_cr"]
                                              / n50_total_mcap * 100).round(2)
        likely_additions["est_passive_inflow_cr"] = (
            likely_additions["est_weight_pct"] / 100 * NIFTY_50_PASSIVE_AUM_CR
        ).round(0)
        likely_deletions["est_weight_pct"] = (likely_deletions["market_cap_cr"]
                                              / n50_total_mcap * 100).round(2)
        likely_deletions["est_passive_outflow_cr"] = (
            likely_deletions["est_weight_pct"] / 100 * NIFTY_50_PASSIVE_AUM_CR
        ).round(0)

        return {
            "as_of": pd.Timestamp.utcnow().isoformat(),
            "universe_size": len(df),
            "n50_total_mcap_cr": int(n50_total_mcap),
            "likely_additions": likely_additions.to_dict("records"),
            "likely_deletions": likely_deletions.to_dict("records"),
            "full_ranking": df[["rank", "ticker", "name", "market_cap_cr",
                                "in_nifty50"]].to_dict("records"),
            "methodology": (
                "Ranks Nifty 50 + Next 50 universe by total market cap (free-float "
                "approximation). Likely deletions = current N50 members ranked > 55. "
                "Likely additions = non-N50 ranked <= 50. Passive flow estimated using "
                f"~Rs {NIFTY_50_PASSIVE_AUM_CR:,} Cr tracked AUM. NSE uses free-float "
                "mcap with specific multipliers; directional accuracy higher than exact."
            ),
            "next_rebalance": "Semi-annual: cut-off Jan / Jul; announcement ~2 weeks "
                              "before, implementation last Friday of Mar / Sep.",
        }
