"""Claude-powered weekly refresh agent for structural risks + catalysts.

For each sector, gathers:
  - Current risk + catalyst list (from structural_risks.py / catalysts.py)
  - Last 14 days of GDELT news headlines for that sector / theme
  - Last 30 days of RBI / SEBI policy items
Asks Claude to propose updates:
  - Severity changes (with reason)
  - New risks / catalysts to ADD (with evidence)
  - Stale ones to RETIRE (no longer relevant)
Outputs a structured DIFF that the user reviews + approves through the UI.
Audit log in SQLite so nothing changes silently.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, CACHE_DIR
from src.data.catalysts import (
    SECTOR_CATALYSTS,
    sector_catalysts,
)
from src.data.gdelt import GDELTAdapter
from src.data.policy import RBIAdapter, SEBIAdapter
from src.data.structural_risks import (
    SECTOR_STRUCTURAL_RISKS,
    for_sector,
)

log = logging.getLogger(__name__)

DB_PATH = CACHE_DIR / "risk_refresh.sqlite"


# ---------------- DB ----------------

@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS refresh_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                refresh_date TEXT NOT NULL,
                sector TEXT NOT NULL,
                kind TEXT NOT NULL,   -- 'risk' or 'catalyst'
                action TEXT NOT NULL, -- 'add' | 'retire' | 'severity_change'
                item TEXT,
                old_value REAL,
                new_value REAL,
                reason TEXT,
                proposed_at TEXT NOT NULL,
                applied_at TEXT,
                status TEXT NOT NULL  -- 'proposed' | 'approved' | 'rejected' | 'applied'
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS ix_refresh_sector ON refresh_log(sector)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_refresh_status ON refresh_log(status)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_refresh_date ON refresh_log(refresh_date)")


# ---------------- Refresh status ----------------

def last_refreshed(sector: str) -> Optional[str]:
    """Return ISO date of the most recent refresh activity for a sector.

    Counts any change that was proposed, approved, or applied (i.e. anything
    NOT rejected). Originally this only counted 'applied' — which created a
    workflow trap because the UI approve flow stops at 'approved' (the
    actual file edit was manual). For the staleness banner to be useful,
    'I looked at this sector recently' is the right signal, not
    'I edited the source file recently'.
    """
    _init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT MAX(COALESCE(applied_at, proposed_at)) AS last FROM refresh_log "
            "WHERE sector = ? AND status IN ('proposed', 'approved', 'applied')",
            (sector,)
        ).fetchone()
    return row["last"] if row and row["last"] else None


def staleness_report(max_age_days: int = 30) -> List[Dict[str, Any]]:
    """Which sectors haven't been refreshed in max_age_days? Returns rows for UI banner."""
    _init_db()
    all_sectors = sorted(set(list(SECTOR_STRUCTURAL_RISKS.keys()) +
                              list(SECTOR_CATALYSTS.keys())))
    out = []
    now = datetime.utcnow()
    for s in all_sectors:
        last = last_refreshed(s)
        if last is None:
            age_days = None
        else:
            try:
                d = datetime.fromisoformat(last)
                age_days = (now - d).days
            except Exception:
                age_days = None
        if age_days is None or age_days >= max_age_days:
            out.append({"sector": s, "last_refreshed": last or "never",
                       "age_days": age_days, "stale": True})
    return out


# ---------------- Refresh agent ----------------

REFRESH_SYSTEM = """You are a senior sell-side equity research head reviewing the structural \
risk + catalyst database for an Indian equity research desk. The desk's current data was \
last refreshed N days ago. Based on supplied news flow + policy items + the current entries, \
your job is to propose UPDATES — not rewrite the whole thing.

For each sector, output a structured JSON with these arrays:
  - severity_changes: [{ "kind": "risk"|"catalyst", "item": "<short label>", "old_severity": 0.x, "new_severity": 0.x, "reason": "..." }]
  - additions: [{ "kind": "risk"|"catalyst", "item": "<short label>", "severity": 0.x, "detail": "...", "evidence": "...short news excerpt..." }]
  - retirements: [{ "kind": "risk"|"catalyst", "item": "<short label>", "reason": "..." }]
  - overall_severity_change: {"kind": "risk"|"catalyst", "old": 0.x, "new": 0.x, "reason": "..."} or null

HARD RULES:
- Be CONSERVATIVE. Most risks/catalysts don't change month-to-month. Empty arrays are fine.
- Only propose change with EVIDENCE — cite the news headline / policy item / earnings event.
- Severity changes typically ±0.05 to ±0.15. Anything larger needs strong justification.
- ADDITION: only if it's a NEW, durable theme — not a one-off news event.
- RETIREMENT: only if the risk/catalyst is unambiguously played out or no longer relevant.
- If unsure, do NOTHING. The default is no change.
- Reasons MUST be specific (data point, headline date). No platitudes.
- Output VALID JSON only — no markdown, no commentary outside the JSON.
"""


@dataclass
class ProposedChange:
    sector: str
    kind: str           # 'risk' | 'catalyst'
    action: str         # 'add' | 'retire' | 'severity_change' | 'overall_change'
    item: Optional[str]
    old_value: Optional[float]
    new_value: Optional[float]
    reason: str


class RiskRefreshAgent:
    def __init__(self):
        self._client = None
        if ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            except Exception as exc:
                log.warning("anthropic init failed: %s", exc)
        self.gdelt = GDELTAdapter()
        self.rbi = RBIAdapter()
        self.sebi = SEBIAdapter()

    @property
    def available(self) -> bool:
        return self._client is not None

    # ---- gather sector context for the prompt ----

    def gather_context(self, sector: str, lookback_days: int = 14) -> Dict[str, Any]:
        """Pull recent news + policy items + current entries for a sector."""
        # GDELT news for sector-themed query
        risks = for_sector(sector)
        catalysts = sector_catalysts(sector)
        # Build a news query from sector label
        theme = risks.get("label") or catalysts.get("label") or sector
        articles = []
        try:
            articles = self.gdelt.articles(f"India {theme}", timespan=f"{lookback_days}d",
                                           max_records=15)
        except Exception as exc:
            log.warning("GDELT failed for sector refresh %s: %s", sector, exc)
        # Recent RBI + SEBI items
        rbi_items, sebi_items = [], []
        try:
            rbi_items = self.rbi.press_releases(15)
        except Exception:
            pass
        try:
            sebi_items = self.sebi.circulars(15)
        except Exception:
            pass

        return {
            "sector": sector,
            "current_risks": risks,
            "current_catalysts": catalysts,
            "recent_news_headlines": [
                {"title": a.get("title"), "date": a.get("date"), "domain": a.get("domain")}
                for a in articles[:10]
            ],
            "recent_rbi": [{"title": r.get("title")} for r in rbi_items[:8]],
            "recent_sebi": [{"title": s.get("title")} for s in sebi_items[:8]],
            "as_of": date.today().isoformat(),
        }

    # ---- main refresh ----

    def propose_changes(self, sector: str, lookback_days: int = 14
                        ) -> List[ProposedChange]:
        """Run Claude + return proposed changes (does NOT apply them)."""
        if not self.available:
            return []
        ctx = self.gather_context(sector, lookback_days)
        user_block = (
            f"Refresh the structural-risk + catalyst entries for sector: **{sector}**.\n\n"
            f"Last refreshed: {last_refreshed(sector) or 'never'}.\n\n"
            f"### Current entries\n```json\n"
            f"{json.dumps({'risks': ctx['current_risks'], 'catalysts': ctx['current_catalysts']}, indent=2, default=str)}\n```\n\n"
            f"### Recent news ({lookback_days}d, GDELT)\n```json\n"
            f"{json.dumps(ctx['recent_news_headlines'], indent=2, default=str)}\n```\n\n"
            f"### Recent RBI press releases\n```json\n"
            f"{json.dumps(ctx['recent_rbi'], indent=2, default=str)}\n```\n\n"
            f"### Recent SEBI circulars\n```json\n"
            f"{json.dumps(ctx['recent_sebi'], indent=2, default=str)}\n```\n\n"
            f"Propose updates as JSON per the system prompt schema."
        )
        try:
            resp = self._client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=2000,
                system=[{"type": "text", "text": REFRESH_SYSTEM,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": [{"type": "text", "text": user_block}]}],
            )
            raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
            # Trim to first {...} JSON block
            start = raw.find("{")
            end = raw.rfind("}")
            if start < 0 or end <= start:
                log.warning("refresh: no JSON in response for %s", sector)
                return []
            try:
                parsed = json.loads(raw[start:end + 1])
            except json.JSONDecodeError as exc:
                log.warning("refresh: JSON parse failed for %s: %s", sector, exc)
                return []
        except Exception as exc:
            log.warning("refresh: Claude call failed for %s: %s", sector, exc)
            return []

        # Convert to ProposedChange list + log as 'proposed'
        proposed: List[ProposedChange] = []
        for sc in parsed.get("severity_changes", []) or []:
            proposed.append(ProposedChange(
                sector=sector, kind=sc.get("kind", "risk"), action="severity_change",
                item=sc.get("item"), old_value=sc.get("old_severity"),
                new_value=sc.get("new_severity"), reason=sc.get("reason", "")))
        for ad in parsed.get("additions", []) or []:
            proposed.append(ProposedChange(
                sector=sector, kind=ad.get("kind", "risk"), action="add",
                item=ad.get("item"), old_value=None,
                new_value=ad.get("severity"),
                reason=f"{ad.get('detail', '')} | evidence: {ad.get('evidence', '')}"))
        for rt in parsed.get("retirements", []) or []:
            proposed.append(ProposedChange(
                sector=sector, kind=rt.get("kind", "risk"), action="retire",
                item=rt.get("item"), old_value=None, new_value=None,
                reason=rt.get("reason", "")))
        oc = parsed.get("overall_severity_change")
        if oc:
            proposed.append(ProposedChange(
                sector=sector, kind=oc.get("kind", "risk"), action="overall_change",
                item="overall_severity", old_value=oc.get("old"),
                new_value=oc.get("new"), reason=oc.get("reason", "")))

        self._log_proposed(proposed)
        return proposed

    def _log_proposed(self, changes: List[ProposedChange]) -> None:
        _init_db()
        now = datetime.utcnow().isoformat()
        today = date.today().isoformat()
        with _conn() as c:
            for ch in changes:
                c.execute(
                    "INSERT INTO refresh_log (refresh_date, sector, kind, action, item, "
                    "old_value, new_value, reason, proposed_at, applied_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'proposed')",
                    (today, ch.sector, ch.kind, ch.action, ch.item,
                     ch.old_value, ch.new_value, ch.reason, now)
                )


# ---------------- Approval / apply ----------------

def list_proposed(sector: Optional[str] = None) -> List[Dict[str, Any]]:
    _init_db()
    q = "SELECT * FROM refresh_log WHERE status = 'proposed'"
    params: tuple = ()
    if sector:
        q += " AND sector = ?"
        params = (sector,)
    q += " ORDER BY proposed_at DESC"
    with _conn() as c:
        return [dict(r) for r in c.execute(q, params).fetchall()]


def mark_status(change_id: int, status: str) -> None:
    """Mark a proposed change as approved / rejected / applied."""
    _init_db()
    if status not in ("approved", "rejected", "applied"):
        raise ValueError(f"invalid status: {status}")
    now = datetime.utcnow().isoformat() if status == "applied" else None
    with _conn() as c:
        c.execute("UPDATE refresh_log SET status = ?, applied_at = ? WHERE id = ?",
                  (status, now, change_id))


def mark_sector_refreshed(sector: str) -> None:
    """Used to write a no-op 'refresh checked' marker even when no changes proposed —
    so the staleness banner correctly resets for that sector."""
    _init_db()
    now = datetime.utcnow().isoformat()
    today = date.today().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO refresh_log (refresh_date, sector, kind, action, item, "
            "old_value, new_value, reason, proposed_at, applied_at, status) "
            "VALUES (?, ?, 'meta', 'no_change_needed', NULL, NULL, NULL, "
            "'Claude reviewed; no changes proposed', ?, ?, 'applied')",
            (today, sector, now, now)
        )


def all_log_entries(limit: int = 200) -> List[Dict[str, Any]]:
    _init_db()
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM refresh_log ORDER BY proposed_at DESC LIMIT ?", (limit,)
        ).fetchall()]


# ---------------- Bulk refresh ----------------

def all_sectors() -> List[str]:
    """Union of every sector defined in either risks or catalysts."""
    return sorted(set(list(SECTOR_STRUCTURAL_RISKS.keys()) +
                       list(SECTOR_CATALYSTS.keys())))


def refresh_batch(sectors: List[str], lookback_days: int = 14,
                  sleep_between: int = 5):
    """Generator that yields per-sector status as it processes.

    Each yield is a dict with: sector, status ('ok'/'no_changes'/'error'),
    proposed_count, error (if any), elapsed_seconds.

    Sleeps `sleep_between` seconds between sectors to avoid rate limits
    (GDELT / Anthropic). For 35 sectors at 5s = ~3 min of pure wait, plus
    ~15-30s of Claude time per sector = total ~12-18 min.
    """
    import time
    agent = RiskRefreshAgent()
    if not agent.available:
        yield {"sector": "<batch>", "status": "error",
               "proposed_count": 0, "error": "ANTHROPIC_API_KEY missing"}
        return

    for i, sec in enumerate(sectors):
        t0 = time.time()
        try:
            proposed = agent.propose_changes(sec, lookback_days=lookback_days)
            if not proposed:
                mark_sector_refreshed(sec)
                yield {"sector": sec, "status": "no_changes",
                       "proposed_count": 0, "error": None,
                       "elapsed_seconds": round(time.time() - t0, 1)}
            else:
                yield {"sector": sec, "status": "ok",
                       "proposed_count": len(proposed), "error": None,
                       "elapsed_seconds": round(time.time() - t0, 1)}
        except Exception as exc:
            yield {"sector": sec, "status": "error",
                   "proposed_count": 0, "error": str(exc)[:200],
                   "elapsed_seconds": round(time.time() - t0, 1)}

        # Be nice to upstream APIs between sectors
        if i < len(sectors) - 1:
            time.sleep(sleep_between)
