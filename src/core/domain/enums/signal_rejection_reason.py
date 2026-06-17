"""SignalRejectionReason — exhaustive set of reasons a signal is not produced."""

from __future__ import annotations

from enum import StrEnum


class SignalRejectionReason(StrEnum):
    DUPLICATE = "DUPLICATE"               # Identical fingerprint within dedup TTL
    SCORE_INELIGIBLE = "SCORE_INELIGIBLE" # ScoreResult.is_eligible is False
    WEAK_SIGNAL = "WEAK_SIGNAL"           # score < min_score OR confidence < min_confidence
    RISK_REJECTED = "RISK_REJECTED"       # Risk Engine rejected the signal
    EXPIRED = "EXPIRED"                   # valid_until <= now at processing time
