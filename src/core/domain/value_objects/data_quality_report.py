"""DataQualityReport — snapshot of data completeness at signal generation time.

Monitoring-only. Never affects scoring, confidence, or trade acceptance.
Stored in signal_analytics for post-hoc feed quality analysis.

Score formula (start at 100, subtract penalties):
  Option chain older than 5 min  -20
  Missing OI data                 -20
  Missing 5m candles              -20
  Missing India VIX               -20
  Missing GEX                     -10
  Stale underlying candles        -20

Alert thresholds:
  < 85 → WARNING
  < 70 → CRITICAL
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

_WARN_THRESHOLD     = 85
_CRITICAL_THRESHOLD = 70


@dataclass(frozen=True)
class DataQualityReport:
    score: int                         # 0–100; 100 = all sources fresh and present
    missing_sources: list[str] = field(default_factory=list)
    stale_feeds: list[str]    = field(default_factory=list)

    @property
    def is_acceptable(self) -> bool:
        return self.score >= _WARN_THRESHOLD

    @property
    def is_critical(self) -> bool:
        return self.score < _CRITICAL_THRESHOLD

    def missing_sources_json(self) -> str:
        return json.dumps(self.missing_sources)

    def to_log_dict(self) -> dict:
        return {
            "data_quality_score": self.score,
            "missing_sources": self.missing_sources,
            "stale_feeds": self.stale_feeds,
        }
