"""Screener base — every framework subclasses this."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class ScreenResult:
    framework: str
    candidates: pd.DataFrame  # columns include ticker, name, sector, score, + framework-specific
    rejected_count: int = 0
    notes: List[str] = field(default_factory=list)
    criteria: Dict[str, str] = field(default_factory=dict)


class Screener:
    """Subclasses implement `run(universe)`."""

    framework: str = "base"

    def run(self, universe: List[str]) -> ScreenResult:
        raise NotImplementedError

    @staticmethod
    def _safe(row: pd.Series, key: str) -> Optional[float]:
        v = row.get(key)
        if v is None:
            return None
        try:
            f = float(v)
            if pd.isna(f):
                return None
            return f
        except (TypeError, ValueError):
            return None
