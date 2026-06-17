"""GraduatedResponseState — frozen value object for the graduated response tier.

Populated from the risk:graduated_response Redis Hash (no TTL).  The state and
multiplier are always consistent: NORMAL→1.0, REDUCED→0.5, PAPER→0.0, KILLED→0.0.

No I/O.  No infrastructure imports.  No async code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.domain.exceptions.risk import RiskInvariantError

_VALID_STATES: frozenset[str] = frozenset({"NORMAL", "REDUCED", "PAPER", "KILLED"})
_STATE_MULTIPLIER: dict[str, float] = {
    "NORMAL": 1.0,
    "REDUCED": 0.5,
    "PAPER": 0.0,
    "KILLED": 0.0,
}


@dataclass(frozen=True, kw_only=True)
class GraduatedResponseState:
    """Immutable representation of the current graduated-response tier.

    Attributes:
        state:                   Current tier: NORMAL | REDUCED | PAPER | KILLED.
        position_size_multiplier: Derived multiplier: NORMAL=1.0, REDUCED=0.5, PAPER/KILLED=0.0.
        activated_at:            UTC timestamp when this tier was entered (None when NORMAL).
        reason:                  Human-readable reason for the tier transition (None when NORMAL).
    """

    state: str
    position_size_multiplier: float
    activated_at: datetime | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.state not in _VALID_STATES:
            raise RiskInvariantError(
                f"state must be one of {sorted(_VALID_STATES)!r}, got {self.state!r}"
            )
        expected = _STATE_MULTIPLIER[self.state]
        if self.position_size_multiplier != expected:
            raise RiskInvariantError(
                f"position_size_multiplier for state={self.state!r} must be {expected}, "
                f"got {self.position_size_multiplier}"
            )
