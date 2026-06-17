"""KillSwitchState — frozen value object for the kill switch snapshot.

Populated from HGETALL system:kill_switch (Hash, no TTL).  When Redis is
unavailable the caller applies FAIL_CLOSED and treats is_active as True —
this VO is only constructed when a successful Redis read occurs.

No I/O.  No infrastructure imports.  No async code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.domain.exceptions.risk import RiskInvariantError

_VALID_ACTIVATED_BY: frozenset[str] = frozenset(
    {"operator", "risk_engine", "dead_mans_switch", "system"}
)


@dataclass(frozen=True, kw_only=True)
class KillSwitchState:
    """Immutable snapshot of the system:kill_switch Redis Hash.

    Attributes:
        is_active:         True when the kill switch is armed.
        activated_at:      UTC timestamp of activation (None when inactive).
        activated_by:      Who/what triggered the activation (None when inactive).
        activation_reason: Human-readable trigger description (None when inactive).
        deactivated_at:    UTC timestamp of most recent deactivation (None if never deactivated).
        deactivated_by:    User/process that deactivated (None if never deactivated).
        deactivation_note: Operator note provided at deactivation (None if never deactivated).
    """

    is_active: bool
    activated_at: datetime | None
    activated_by: str | None
    activation_reason: str | None
    deactivated_at: datetime | None
    deactivated_by: str | None
    deactivation_note: str | None

    def __post_init__(self) -> None:
        if self.activated_by is not None and self.activated_by not in _VALID_ACTIVATED_BY:
            raise RiskInvariantError(
                f"activated_by must be one of {sorted(_VALID_ACTIVATED_BY)!r}, "
                f"got {self.activated_by!r}"
            )
