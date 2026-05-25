"""GDELT DOC API adapter — free global news + sentiment.

Two surfaces:
  - articles(query, timespan)   : recent headlines
  - tone(query, timespan)       : aggregated tone distribution + summary stats

GDELT can be flaky / slow — adapter degrades to empty results on timeout rather than
exploding the calling view.
"""
from __future__ import annotations

import logging
from statistics import mean
from typing import Any, Dict, List, Optional

import requests

from src.data.base import DataAdapter

log = logging.getLogger(__name__)

GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"

# Headlines come from these domains preferentially. We don't filter strictly — GDELT
# query syntax is unwieldy — but we score domain quality in the headline list.
QUALITY_DOMAINS = {
    "moneycontrol.com": 1.0,
    "livemint.com": 1.0,
    "business-standard.com": 1.0,
    "economictimes.indiatimes.com": 1.0,
    "financialexpress.com": 1.0,
    "thehindubusinessline.com": 1.0,
    "reuters.com": 1.0,
    "bloomberg.com": 1.0,
    "ft.com": 1.0,
    "ndtvprofit.com": 0.9,
    "cnbctv18.com": 0.9,
    "businesstoday.in": 0.8,
    "outlookbusiness.com": 0.8,
}


class GDELTAdapter(DataAdapter):
    namespace = "gdelt"
    default_ttl = 6 * 3600  # 6h — news moves but not so fast as to need <hourly refresh

    @staticmethod
    def _build_query(entity: str, country: str = "IN") -> str:
        """Build a moderately specific GDELT query."""
        cleaned = entity.strip().replace('"', "")
        return f'"{cleaned}" sourcecountry:{country}'

    def articles(self, entity: str, timespan: str = "14d", max_records: int = 30,
                 country: str = "IN") -> List[Dict[str, Any]]:
        """Recent headlines for an entity (company name or theme). Date-desc."""
        q = self._build_query(entity, country)

        def _load():
            try:
                r = requests.get(GDELT_DOC, params={
                    "query": q, "mode": "artlist", "maxrecords": str(max_records),
                    "format": "json", "sort": "datedesc", "timespan": timespan,
                }, timeout=45)
                r.raise_for_status()
                data = r.json()
            except Exception as exc:
                log.warning("GDELT artlist failed for %s: %s", entity, exc)
                return []
            arts = data.get("articles", []) or []
            # Score by domain quality and language preference (English first)
            for a in arts:
                dom = (a.get("domain") or "").lower()
                lang = (a.get("language") or "").lower()
                a["quality_score"] = QUALITY_DOMAINS.get(dom, 0.3)
                if lang == "english":
                    a["quality_score"] += 0.3
            arts.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
            # Trim to most useful fields
            return [{
                "title": a.get("title"),
                "url": a.get("url"),
                "domain": a.get("domain"),
                "language": a.get("language"),
                "date": (a.get("seendate") or "")[:8],
                "quality_score": a.get("quality_score"),
            } for a in arts]

        return self._cached(("articles", entity, timespan, country, max_records), _load)

    def tone(self, entity: str, timespan: str = "14d", country: str = "IN") -> Dict[str, Any]:
        """Aggregated tone distribution + summary stats.

        GDELT tone ranges roughly -10 (very negative) to +10 (very positive).
        We return: total_articles, mean_tone, pct_positive, pct_negative, distribution.
        """
        q = self._build_query(entity, country)

        def _load():
            try:
                r = requests.get(GDELT_DOC, params={
                    "query": q, "mode": "tonechart", "format": "json", "timespan": timespan,
                }, timeout=60)
                r.raise_for_status()
                data = r.json()
            except Exception as exc:
                log.warning("GDELT tonechart failed for %s: %s", entity, exc)
                return {"total_articles": 0, "mean_tone": None, "pct_positive": None,
                        "pct_negative": None, "distribution": [], "error": str(exc)}
            bins = data.get("tonechart", []) or []
            total = sum(b.get("count", 0) for b in bins)
            if total == 0:
                return {"total_articles": 0, "mean_tone": None, "pct_positive": None,
                        "pct_negative": None, "distribution": []}
            weighted = sum(b.get("bin", 0) * b.get("count", 0) for b in bins)
            mean_tone = round(weighted / total, 2)
            pos = sum(b["count"] for b in bins if b.get("bin", 0) > 0)
            neg = sum(b["count"] for b in bins if b.get("bin", 0) < 0)
            return {
                "total_articles": total,
                "mean_tone": mean_tone,
                "pct_positive": round(100 * pos / total, 1),
                "pct_negative": round(100 * neg / total, 1),
                "distribution": [{"bin": b.get("bin"), "count": b.get("count")} for b in bins],
            }

        return self._cached(("tone", entity, timespan, country), _load)

    def sentiment_for_ticker(self, ticker: str, company_name: Optional[str] = None,
                             timespan: str = "14d") -> Dict[str, Any]:
        """Convenience: pulls tone + top-5 quality headlines for a ticker/company combo."""
        entity = company_name or ticker
        tone = self.tone(entity, timespan=timespan)
        arts = self.articles(entity, timespan=timespan, max_records=20)
        return {
            "ticker": ticker.upper(),
            "entity_queried": entity,
            "timespan": timespan,
            "tone": tone,
            "top_headlines": arts[:5],
        }
