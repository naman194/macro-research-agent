"""RBI + SEBI policy scrapers.

RBI: scrapes the press releases listing page. Captures the headline + URL + date.
     RBI groups releases under <h3> date headings; we walk anchors with prid= params.
SEBI: scrapes the master-circulars listing page. Captures circular title + URL.

Both adapters cache for 6h since policy publishes daily at most.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from src.data.base import DataAdapter

log = logging.getLogger(__name__)


RBI_PR_URL = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
SEBI_MASTER_URL = ("https://www.sebi.gov.in/sebiweb/home/HomeAction.do"
                   "?doListing=yes&sid=1&ssid=6&smid=0")
SEBI_CIRCULARS_URL = ("https://www.sebi.gov.in/sebiweb/home/HomeAction.do"
                      "?doListing=yes&sid=1&ssid=7&smid=0")

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class RBIAdapter(DataAdapter):
    namespace = "rbi"
    default_ttl = 6 * 3600

    def press_releases(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Most-recent press releases. Returns title, url, prid, date if parseable."""
        def _load():
            try:
                r = requests.get(RBI_PR_URL, headers={"User-Agent": _UA}, timeout=30)
                r.raise_for_status()
            except Exception as exc:
                log.warning("RBI fetch failed: %s", exc)
                return []
            soup = BeautifulSoup(r.text, "lxml")
            out: List[Dict[str, Any]] = []
            current_date: Optional[str] = None
            # Walk the document in order; track the last date heading seen
            for el in soup.find_all(["h3", "a"]):
                if el.name == "h3":
                    text = el.get_text(strip=True)
                    if re.match(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$", text):
                        current_date = text
                        continue
                    # Section headings like "2026" reset date
                    if re.match(r"^\d{4}$", text):
                        current_date = None
                        continue
                if el.name == "a":
                    href = el.get("href", "")
                    if "prid=" not in href:
                        continue
                    title = el.get_text(strip=True)
                    if not title or title.lower() == "press releases":
                        continue
                    prid_match = re.search(r"prid=(\d+)", href)
                    prid = prid_match.group(1) if prid_match else None
                    full_url = href if href.startswith("http") else f"https://www.rbi.org.in/Scripts/{href.lstrip('./')}"
                    out.append({
                        "title": title,
                        "url": full_url,
                        "prid": prid,
                        "date": current_date,
                    })
                    if len(out) >= limit:
                        break
            return out

        return self._cached(("press_releases", limit), _load)


class SEBIAdapter(DataAdapter):
    namespace = "sebi"
    default_ttl = 6 * 3600

    def master_circulars(self, limit: int = 25) -> List[Dict[str, Any]]:
        return self._scrape_listing(SEBI_MASTER_URL, ("master_circulars", limit), limit)

    def circulars(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self._scrape_listing(SEBI_CIRCULARS_URL, ("circulars", limit), limit)

    def _scrape_listing(self, url: str, cache_key: tuple, limit: int) -> List[Dict[str, Any]]:
        def _load():
            try:
                r = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
                r.raise_for_status()
            except Exception as exc:
                log.warning("SEBI fetch failed for %s: %s", url, exc)
                return []
            soup = BeautifulSoup(r.text, "lxml")
            out = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/legal/" not in href.lower():
                    continue
                title = a.get_text(strip=True)
                if not title:
                    continue
                # Pull a date hint from URL path like /aug-2026/
                m = re.search(r"/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)-(\d{4})/",
                              href, flags=re.I)
                date_hint = f"{m.group(1).title()} {m.group(2)}" if m else None
                out.append({"title": title, "url": href, "date_hint": date_hint})
                if len(out) >= limit:
                    break
            return out

        return self._cached(cache_key, _load)


def all_policy_items(limit_per_source: int = 25) -> List[Dict[str, Any]]:
    """Convenience for the policy view: union of RBI + SEBI items, tagged by source."""
    out = []
    try:
        for item in RBIAdapter().press_releases(limit_per_source):
            item["source"] = "RBI"
            out.append(item)
    except Exception as exc:
        log.warning("RBI source failed: %s", exc)
    try:
        for item in SEBIAdapter().circulars(limit_per_source):
            item["source"] = "SEBI"
            out.append(item)
    except Exception as exc:
        log.warning("SEBI circulars failed: %s", exc)
    try:
        for item in SEBIAdapter().master_circulars(15):
            item["source"] = "SEBI (Master)"
            out.append(item)
    except Exception as exc:
        log.warning("SEBI master failed: %s", exc)
    return out
