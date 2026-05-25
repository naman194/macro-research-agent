"""Macro economic calendar — India + global rate-setting + data release schedule.

Sources:
  - Recurring India events (CPI, IIP, WPI, GDP, Trade Balance) on standard publishing
    dates from MOSPI / RBI. We hardcode the schedule and tag with last-known print.
  - RBI MPC dates from RBI Press Releases adapter (Bi-Monthly).
  - Global central bank meeting dates (Fed FOMC, ECB, BoE) — hardcoded for current cycle.

Output: list of upcoming events with date, country, indicator, importance,
last print value, consensus (where surfaced), source URL.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from src.data.base import DataAdapter
from src.data.policy import RBIAdapter

log = logging.getLogger(__name__)


# ---- Hardcoded recurring schedule (refresh annually) ----

# Days-of-month each India indicator typically releases
_INDIA_RECURRING = [
    {"indicator": "India CPI Inflation", "country": "IN", "importance": "high",
     "day_of_month": 12, "publisher": "MOSPI",
     "url": "https://mospi.gov.in/cpi"},
    {"indicator": "India IIP (Industrial Production)", "country": "IN", "importance": "medium",
     "day_of_month": 12, "publisher": "MOSPI",
     "url": "https://mospi.gov.in/iip"},
    {"indicator": "India WPI Inflation", "country": "IN", "importance": "medium",
     "day_of_month": 14, "publisher": "Office of Economic Adviser",
     "url": "https://eaindustry.nic.in/"},
    {"indicator": "India Trade Balance", "country": "IN", "importance": "medium",
     "day_of_month": 15, "publisher": "Commerce Ministry",
     "url": "https://commerce.gov.in/"},
    {"indicator": "India PMI Manufacturing (HSBC)", "country": "IN", "importance": "medium",
     "day_of_month": 1, "publisher": "S&P Global / HSBC",
     "url": "https://www.pmi.spglobal.com/"},
    {"indicator": "India PMI Services (HSBC)", "country": "IN", "importance": "medium",
     "day_of_month": 3, "publisher": "S&P Global / HSBC",
     "url": "https://www.pmi.spglobal.com/"},
]

# Quarterly schedule (GDP releases at end of Feb / May / Aug / Nov for Dec/Mar/Jun/Sep quarter)
_INDIA_QUARTERLY = [
    {"indicator": "India GDP (Quarterly)", "country": "IN", "importance": "high",
     "months": [2, 5, 8, 11], "day_of_month": 28,
     "publisher": "MOSPI", "url": "https://mospi.gov.in/gdp"},
]

# RBI MPC — bi-monthly. Approximate near-term dates (NSE quirk: may shift by 1-2d).
# Refresh once per year from RBI calendar.
RBI_MPC_DATES_2026 = [
    "2026-02-07", "2026-04-09", "2026-06-06", "2026-08-08",
    "2026-10-01", "2026-12-05",
]

# Fed FOMC — 8 meetings/year. Refresh annually from Fed schedule.
FED_FOMC_DATES_2026 = [
    "2026-01-29", "2026-03-19", "2026-04-30", "2026-06-18",
    "2026-07-30", "2026-09-17", "2026-10-29", "2026-12-10",
]

# ECB and BoE — refresh annually.
ECB_DATES_2026 = ["2026-01-22", "2026-03-12", "2026-04-16", "2026-06-04",
                  "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17"]
BOE_DATES_2026 = ["2026-02-05", "2026-03-19", "2026-05-07", "2026-06-18",
                  "2026-08-06", "2026-09-17", "2026-11-05", "2026-12-17"]


@dataclass
class CalendarEvent:
    event_date: str
    country: str
    indicator: str
    importance: str
    last_print: Optional[str]
    consensus: Optional[str]
    publisher: str
    url: str


class EconCalendarAdapter(DataAdapter):
    namespace = "econ_calendar"
    default_ttl = 24 * 3600

    def __init__(self):
        super().__init__()
        self.rbi = RBIAdapter()

    def _india_recurring_events(self, lookahead_days: int = 30) -> List[CalendarEvent]:
        """Generate upcoming India recurring events based on day-of-month schedule."""
        today = date.today()
        end = today + timedelta(days=lookahead_days)
        events: List[CalendarEvent] = []

        def _next_dom(target_dom: int, start: date) -> date:
            year, month = start.year, start.month
            try:
                d = date(year, month, target_dom)
            except ValueError:
                d = date(year, month, 28)
            if d < start:
                # Roll to next month
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
                try:
                    d = date(year, month, target_dom)
                except ValueError:
                    d = date(year, month, 28)
            return d

        for tmpl in _INDIA_RECURRING:
            dom = tmpl["day_of_month"]
            cur = today
            while True:
                d = _next_dom(dom, cur)
                if d > end:
                    break
                events.append(CalendarEvent(
                    event_date=d.isoformat(),
                    country=tmpl["country"], indicator=tmpl["indicator"],
                    importance=tmpl["importance"], last_print=None, consensus=None,
                    publisher=tmpl["publisher"], url=tmpl["url"],
                ))
                cur = d + timedelta(days=1)

        for tmpl in _INDIA_QUARTERLY:
            for m in tmpl["months"]:
                try:
                    d = date(today.year, m, tmpl["day_of_month"])
                    if today <= d <= end:
                        events.append(CalendarEvent(
                            event_date=d.isoformat(),
                            country=tmpl["country"], indicator=tmpl["indicator"],
                            importance=tmpl["importance"], last_print=None,
                            consensus=None,
                            publisher=tmpl["publisher"], url=tmpl["url"],
                        ))
                except ValueError:
                    continue
        return events

    def _central_bank_events(self, lookahead_days: int = 60) -> List[CalendarEvent]:
        today = date.today()
        end = today + timedelta(days=lookahead_days)
        all_dates = (
            [("IN", "RBI MPC", "high", "Reserve Bank of India",
              "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx", d)
             for d in RBI_MPC_DATES_2026]
            + [("US", "Fed FOMC", "high", "Federal Reserve",
                "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", d)
               for d in FED_FOMC_DATES_2026]
            + [("EU", "ECB Rate Decision", "medium", "European Central Bank",
                "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html", d)
               for d in ECB_DATES_2026]
            + [("UK", "BoE Rate Decision", "medium", "Bank of England",
                "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates", d)
               for d in BOE_DATES_2026]
        )
        out = []
        for country, ind, imp, pub, url, dstr in all_dates:
            try:
                d = date.fromisoformat(dstr)
            except ValueError:
                continue
            if today <= d <= end:
                out.append(CalendarEvent(d.isoformat(), country, ind, imp,
                                        None, None, pub, url))
        return out

    def upcoming(self, lookahead_days: int = 30) -> List[Dict[str, Any]]:
        """Combined upcoming-events list, sorted by date."""
        events = self._india_recurring_events(lookahead_days)
        events += self._central_bank_events(lookahead_days)
        events.sort(key=lambda e: (e.event_date, -1 if e.importance == "high" else 0))
        return [e.__dict__ for e in events]

    def upcoming_summary_line(self, days: int = 14) -> str:
        """One-line summary for daily brief — next 2-3 high-importance events."""
        evs = [e for e in self.upcoming(days) if e["importance"] == "high"]
        if not evs:
            return "No high-importance macro events in next 2 weeks."
        return " · ".join(
            f"{e['event_date']}: {e['indicator']} ({e['country']})"
            for e in evs[:4]
        )
