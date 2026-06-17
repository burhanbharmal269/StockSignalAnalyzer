"""SignalFingerprint — SHA-256 identity of a specific signal pattern.

The fingerprint is used by the Confidence Engine to look up historical
accuracy of patterns with the same (regime, score_bucket, direction,
top_2_components, vix_bucket) combination.

Reference: docs/21_SIGNAL_ENGINE.md §Stage 3 — Historical Accuracy Adjustment
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

_VALID_SCORE_BUCKETS = frozenset({"STRONG", "STANDARD"})
_VALID_DIRECTIONS = frozenset({"LONG", "SHORT"})
_VALID_VIX_BUCKETS = frozenset({"<14", "14-18", "18-22", ">22", "unknown"})


@dataclass(frozen=True)
class SignalFingerprint:
    """Canonical five-field identity of a signal pattern.

    ``sha256`` is derived deterministically from the five input fields and
    is stored with every signal and every signal_performance_stats record.
    Two fingerprints are identical if and only if all five fields match.
    """

    regime: str
    score_bucket: str                     # "STRONG" | "STANDARD"
    direction: str                        # "LONG" | "SHORT"
    top_2_components: tuple[str, str]     # sorted alphabetically
    vix_bucket: str                       # "<14" | "14-18" | "18-22" | ">22" | "unknown"
    sha256: str = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.score_bucket not in _VALID_SCORE_BUCKETS:
            raise ValueError(f"Invalid score_bucket: {self.score_bucket!r}")
        if self.direction not in _VALID_DIRECTIONS:
            raise ValueError(f"Invalid direction: {self.direction!r}")
        if self.vix_bucket not in _VALID_VIX_BUCKETS:
            raise ValueError(f"Invalid vix_bucket: {self.vix_bucket!r}")
        canonical = json.dumps(
            {
                "direction": self.direction,
                "regime": self.regime,
                "score_bucket": self.score_bucket,
                "top_2_components": sorted(self.top_2_components),
                "vix_bucket": self.vix_bucket,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        object.__setattr__(self, "sha256", hashlib.sha256(canonical.encode()).hexdigest())

    @staticmethod
    def score_bucket_for(adjusted_score: float) -> str:
        return "STRONG" if adjusted_score >= 85.0 else "STANDARD"

    @staticmethod
    def vix_bucket_for(india_vix: float | None) -> str:
        if india_vix is None:
            return "unknown"
        if india_vix < 14.0:
            return "<14"
        if india_vix < 18.0:
            return "14-18"
        if india_vix < 22.0:
            return "18-22"
        return ">22"


def compute_signal_fingerprint(
    regime: str,
    adjusted_score: float,
    direction: str,
    top_2_components: tuple[str, str],
    india_vix: float | None,
) -> str:
    """Compute the SHA-256 signal fingerprint from raw input values.

    Convenience wrapper around SignalFingerprint for callers that have
    the raw score and VIX values rather than pre-bucketed strings.
    """
    fp = SignalFingerprint(
        regime=regime,
        score_bucket=SignalFingerprint.score_bucket_for(adjusted_score),
        direction=direction,
        top_2_components=top_2_components,
        vix_bucket=SignalFingerprint.vix_bucket_for(india_vix),
    )
    return fp.sha256
