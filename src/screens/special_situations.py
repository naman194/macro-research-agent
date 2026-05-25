"""Special Situations screener — catalyst-driven, event-led ideas.

Uses NSE upcoming-events feed. Filters for high-signal corporate actions:
buybacks, bonus issues, stock splits, fund raising (QIP/preferential).
Each event gets a category weight; final score blends weight and proximity-to-event.

Phase 3 should extend with demerger / open-offer / scheme-of-arrangement data
which lives on a separate NSE URL (not in the events feed).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from src.config import TTL_FILINGS
from src.data.base import DataAdapter
from src.screens.base import Screener, ScreenResult

log = logging.getLogger(__name__)


EVENT_WEIGHTS: Dict[str, float] = {
    "buyback": 90.0,
    "bonus": 70.0,
    "stock_split": 55.0,
    "fund_raising": 45.0,
    "dividend_only": 20.0,
}


def _classify(purpose: str, bm_desc: Optional[str]) -> List[str]:
    """Return list of category tags for an event row."""
    text = " ".join([(purpose or ""), (bm_desc or "")]).lower()
    tags = []
    if re.search(r"buy.?back", text):
        tags.append("buyback")
    if re.search(r"\bbonus\b", text):
        tags.append("bonus")
    if re.search(r"stock split|sub.?division", text):
        tags.append("stock_split")
    if re.search(r"fund raising|qip|preferential|rights issue|debenture|ncd issue", text):
        tags.append("fund_raising")
    # Dividend alone (no other catalyst) — low signal
    if not tags and re.search(r"\bdividend\b", text):
        tags.append("dividend_only")
    return tags


class SpecialSituationsScreener(Screener):
    framework = "special_situations"
    namespace = "special_sit"

    def __init__(self, universe: Optional[List[str]] = None):
        self._universe = set(u.upper() for u in (universe or []))
        self._nsepython = None
        try:
            import nsepython
            self._nsepython = nsepython
        except Exception as exc:
            log.warning("nsepython missing; special-situations limited: %s", exc)

    def run(self, universe: List[str] = None) -> ScreenResult:
        """If `universe` is supplied, restrict to those tickers; else scan all events."""
        if universe:
            self._universe = set(u.upper() for u in universe)

        if not self._nsepython:
            return ScreenResult(framework=self.framework, candidates=pd.DataFrame(),
                                notes=["nsepython unavailable"], criteria=self._criteria())

        events = _fetch_events_cached(self._nsepython)
        if events.empty:
            return ScreenResult(framework=self.framework, candidates=pd.DataFrame(),
                                notes=["NSE events feed empty"], criteria=self._criteria())

        # Classify each event
        events = events.copy()
        events["tags"] = events.apply(
            lambda r: _classify(r.get("purpose"), r.get("bm_desc")), axis=1
        )
        events = events[events["tags"].apply(lambda t: any(x != "dividend_only" for x in t) or len(t) > 0)]

        # Optional universe filter
        if self._universe:
            events = events[events["symbol"].str.upper().isin(self._universe)]

        # Drop dividend-only unless we explicitly want them; keep but down-weight
        rows = []
        today = datetime.utcnow().date()
        for _, ev in events.iterrows():
            tags = ev["tags"]
            if not tags:
                continue
            top_tag = max(tags, key=lambda t: EVENT_WEIGHTS.get(t, 0))
            weight = EVENT_WEIGHTS.get(top_tag, 0)
            try:
                dt = datetime.strptime(str(ev["date"]), "%d-%b-%Y").date()
            except Exception:
                dt = today
            days_to_event = (dt - today).days
            # Proximity bonus: events 0-14 days out get max bonus, taper to 0 by 90 days
            proximity = max(0, 1 - (max(days_to_event, 0) / 90))
            score = round(weight * (0.6 + 0.4 * proximity), 2)
            rows.append({
                "ticker": ev["symbol"],
                "name": ev.get("company"),
                "event_type": top_tag,
                "all_tags": ",".join(tags),
                "event_date": dt.isoformat(),
                "days_out": days_to_event,
                "purpose": ev.get("purpose"),
                "description": (ev.get("bm_desc") or "")[:300],
                "score": score,
            })

        if not rows:
            return ScreenResult(framework=self.framework, candidates=pd.DataFrame(),
                                notes=["No qualifying special-situation events in feed"],
                                criteria=self._criteria())

        df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
        return ScreenResult(
            framework=self.framework,
            candidates=df,
            notes=[f"Found {len(df)} special-situation events across {df['ticker'].nunique()} tickers."],
            criteria=self._criteria(),
        )

    def _criteria(self):
        return {
            "event_types": list(EVENT_WEIGHTS.keys()),
            "weights": EVENT_WEIGHTS,
            "score_formula": "weight × (0.6 + 0.4 × proximity_to_event)",
            "proximity_window_days": 90,
            "source": "NSE upcoming board-meeting events feed (nsepython.nse_events)",
        }


# Module-level cached fetcher so we don't re-pull the 750-row feed per screener call.
_events_cache: Dict[str, pd.DataFrame] = {}
_events_fetched_at: Dict[str, float] = {}


def _fetch_events_cached(nsepython_module) -> pd.DataFrame:
    import time
    now = time.time()
    if "df" in _events_cache and (now - _events_fetched_at.get("ts", 0)) < TTL_FILINGS:
        return _events_cache["df"]
    try:
        df = nsepython_module.nse_events()
    except Exception as exc:
        log.warning("nse_events fetch failed: %s", exc)
        return pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    _events_cache["df"] = df
    _events_fetched_at["ts"] = now
    return df


# DataAdapter shim so callers can subscribe to the feed directly (used by Sentiment view).
class NSEEventsAdapter(DataAdapter):
    namespace = "nse_events"
    default_ttl = TTL_FILINGS

    def __init__(self) -> None:
        super().__init__()
        self._nsepython = None
        try:
            import nsepython
            self._nsepython = nsepython
        except Exception:
            pass

    def all_events(self) -> pd.DataFrame:
        if not self._nsepython:
            return pd.DataFrame()
        return _fetch_events_cached(self._nsepython)
