"""Management credibility — longitudinal analysis of stored concall extractions.

What this answers:
  Did this management's narrative hold up over 4-12 quarters? Is the tone
  consistent or does it whiplash? Are the same concerns re-appearing call after
  call (unresolved)? How much guidance has been withdrawn or lowered vs raised?

What this DOESN'T answer (yet):
  Whether the *numeric* guidance was actually delivered. That requires joining
  with subsequent quarterly results (revenue, margin, capex actuals) — a v2
  effort. The current 'credibility' is *internal consistency* — does management
  contradict itself or chronic-issue around the same topic.

Methodology:
  Score = weighted sum of four signals, each 0-100 (higher = more credible):
    - tone_stability:  consecutive-quarter tone change penalty
    - concern_resolution: how quickly recurring concerns drop off the list
    - guidance_discipline: % guidance items 'reiterated' or 'raised' vs 'lowered' or 'withdrawn'
    - pressure_recurrence: how often the same topic shows up as a pressure point

Needs 3+ stored calls to be meaningful. With 2, we still report what we can.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.data.concall_archive import ConcallArchive, ConcallRecord

log = logging.getLogger(__name__)


# Tone ordinal scale — used for change/stability scoring.
TONE_ORDINAL = {
    "bullish": 5, "confident": 4, "neutral": 3,
    "cautious": 2, "hesitant": 1, "defensive": 1,
}


@dataclass
class CredibilityReport:
    ticker: str
    credibility_score: int          # 0-100
    tone_stability: int
    concern_resolution: int
    guidance_discipline: int
    pressure_recurrence: int
    recurring_concerns: Dict[str, int] = field(default_factory=dict)
    guidance_churn: Dict[str, int] = field(default_factory=dict)
    recurring_pressure: Dict[str, int] = field(default_factory=dict)
    summary: str = ""
    records: List[ConcallRecord] = field(default_factory=list)


def _tone_stability(records: List[ConcallRecord]) -> int:
    """Penalise large tone swings between consecutive quarters."""
    ordinals = []
    for r in records:
        if r.tone and r.tone.lower() in TONE_ORDINAL:
            ordinals.append(TONE_ORDINAL[r.tone.lower()])
    if len(ordinals) < 2:
        return 60  # default — not enough data, neither reward nor punish
    # Average absolute change between consecutive calls
    diffs = [abs(ordinals[i] - ordinals[i-1]) for i in range(1, len(ordinals))]
    avg_diff = sum(diffs) / len(diffs)
    # 0 diff = 100, 4 diff = 0 (max tone gap is 4 on our scale)
    return int(max(0, min(100, 100 - avg_diff * 25)))


def _normalise_concern(s: str) -> str:
    """Crude fuzzy key for concern matching — lowercase + strip stopwords."""
    if not s: return ""
    s = s.lower().strip()
    for tok in ("the ", "a ", "an ", "in ", "of ", "for ", "to ", "on ", "and "):
        s = s.replace(tok, " ")
    return " ".join(s.split())[:50]   # truncate to first 50 chars for matching


def _concern_resolution(records: List[ConcallRecord]) -> tuple[int, Dict[str, int]]:
    """How often do the same concerns recur quarter after quarter? Persistent
    concerns (3+ quarters) signal unresolved issues = lower credibility."""
    seen_in: Dict[str, set] = defaultdict(set)
    for r in records:
        for c in (r.concerns or []):
            key = _normalise_concern(c)
            if key:
                seen_in[key].add(r.quarter)

    recurring = {k: len(v) for k, v in seen_in.items() if len(v) >= 2}
    if not records:
        return 60, recurring

    n_concerns_total = sum(len(r.concerns or []) for r in records) or 1
    n_recurring_appearances = sum(v for v in recurring.values())
    recurring_share = n_recurring_appearances / n_concerns_total

    # 0% recurring = 100, 60%+ recurring = 0
    score = int(max(0, min(100, 100 - recurring_share * 167)))
    return score, dict(sorted(recurring.items(), key=lambda x: -x[1])[:10])


def _guidance_discipline(records: List[ConcallRecord]) -> tuple[int, Dict[str, int]]:
    """Distribution of guidance directions across all calls.
    new/reiterated/raised = good signal; lowered/withdrawn = bad signal."""
    counter: Counter = Counter()
    for r in records:
        for g in (r.guidance or []):
            d = (g.get("direction") or "").lower().strip()
            if d:
                counter[d] += 1

    total = sum(counter.values())
    if total == 0:
        return 60, dict(counter)

    good = counter.get("reiterated", 0) + counter.get("raised", 0) + counter.get("new", 0) * 0.5
    bad = counter.get("lowered", 0) + counter.get("withdrawn", 0) * 1.5
    # Discipline score: 100 when all good, 0 when all bad
    if good + bad == 0:
        return 60, dict(counter)
    raw = good / (good + bad)
    score = int(max(0, min(100, raw * 100)))
    return score, dict(counter)


def _pressure_recurrence(records: List[ConcallRecord]) -> tuple[int, Dict[str, int]]:
    """How often the same topic shows up as an analyst pressure point.
    Chronic pressure = chronic unresolved issue = lower credibility."""
    topic_quarters: Dict[str, set] = defaultdict(set)
    for r in records:
        for pp in (r.pressure_points or []):
            topic = _normalise_concern(pp.get("topic") or "")
            if topic:
                topic_quarters[topic].add(r.quarter)

    recurring = {k: len(v) for k, v in topic_quarters.items() if len(v) >= 2}
    total_topics = sum(len(r.pressure_points or []) for r in records) or 1
    recurring_count = sum(v for v in recurring.values())
    share = recurring_count / total_topics
    score = int(max(0, min(100, 100 - share * 150)))
    return score, dict(sorted(recurring.items(), key=lambda x: -x[1])[:8])


# Weights — credibility is mostly about not contradicting yourself (tone +
# concern resolution) and about being disciplined with the numbers.
WEIGHTS = {
    "tone_stability":      0.25,
    "concern_resolution":  0.30,
    "guidance_discipline": 0.30,
    "pressure_recurrence": 0.15,
}


def credibility_report(ticker: str,
                       archive: Optional[ConcallArchive] = None) -> CredibilityReport:
    archive = archive or ConcallArchive()
    records = archive.list_for_ticker(ticker, limit=12)
    # Reverse to chronological order (oldest first) for trend analysis
    records = list(reversed(records))

    if not records:
        return CredibilityReport(ticker=ticker, credibility_score=0,
                                 tone_stability=0, concern_resolution=0,
                                 guidance_discipline=0, pressure_recurrence=0,
                                 summary="No calls stored for this ticker.")

    ts = _tone_stability(records)
    cr, recurring_concerns = _concern_resolution(records)
    gd, churn = _guidance_discipline(records)
    pr, recurring_pressure = _pressure_recurrence(records)

    composite = int(
        WEIGHTS["tone_stability"] * ts +
        WEIGHTS["concern_resolution"] * cr +
        WEIGHTS["guidance_discipline"] * gd +
        WEIGHTS["pressure_recurrence"] * pr
    )

    # Human summary — what drove the score
    bits = []
    if len(records) < 3:
        bits.append(f"only {len(records)} call(s) in archive — score is provisional")
    if ts >= 75: bits.append("tone consistent across quarters")
    elif ts <= 40: bits.append("tone has swung sharply across quarters")
    if cr <= 40 and recurring_concerns:
        top_c = list(recurring_concerns.keys())[0]
        bits.append(f"unresolved recurring concern: '{top_c[:40]}…' (in {recurring_concerns[top_c]} calls)")
    elif cr >= 75:
        bits.append("concerns drop off list cleanly (issues being addressed)")
    if gd <= 40 and churn:
        n_low = churn.get("lowered", 0) + churn.get("withdrawn", 0)
        n_tot = sum(churn.values())
        bits.append(f"{n_low}/{n_tot} guidance items lowered or withdrawn (discipline weak)")
    elif gd >= 75:
        bits.append("guidance discipline strong (mostly reiterated / raised)")
    if pr <= 40 and recurring_pressure:
        bits.append(f"analysts keep pressing on the same topics — chronic friction")

    summary = "; ".join(bits) if bits else "internal consistency across the call history."
    summary = summary[0].upper() + summary[1:] + "."

    # Re-reverse records to newest-first for display
    return CredibilityReport(
        ticker=ticker,
        credibility_score=composite,
        tone_stability=ts,
        concern_resolution=cr,
        guidance_discipline=gd,
        pressure_recurrence=pr,
        recurring_concerns=recurring_concerns,
        guidance_churn=churn,
        recurring_pressure=recurring_pressure,
        summary=summary,
        records=list(reversed(records)),
    )
