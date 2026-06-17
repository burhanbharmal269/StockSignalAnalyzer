"""SignalState — unified signal lifecycle state machine.

States derived from docs/16_SIGNAL_SCORING_ENGINE.md,
docs/21_SIGNAL_ENGINE.md, docs/22_OMS_DESIGN.md (audit-resolved version).
"""

from __future__ import annotations

from enum import StrEnum


class SignalState(StrEnum):
    # Active states (non-terminal)
    PENDING = "PENDING"
    SCORING = "SCORING"
    SCORED = "SCORED"
    RISK_PENDING = "RISK_PENDING"
    RISK_APPROVED = "RISK_APPROVED"
    FORWARDED = "FORWARDED"

    # Terminal states
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    RISK_REJECTED = "RISK_REJECTED"
    WEAK_SIGNAL = "WEAK_SIGNAL"  # score < 70 OR confidence < 65
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATES


_TERMINAL_STATES: frozenset[SignalState] = frozenset(
    {
        SignalState.EXECUTED,
        SignalState.EXPIRED,
        SignalState.CANCELLED,
        SignalState.RISK_REJECTED,
        SignalState.WEAK_SIGNAL,
        SignalState.FAILED,
    }
)

# Every valid transition. Attempting any unlisted transition raises SignalStateError.
VALID_SIGNAL_TRANSITIONS: dict[SignalState, frozenset[SignalState]] = {
    SignalState.PENDING: frozenset(
        {SignalState.SCORING, SignalState.CANCELLED, SignalState.FAILED}
    ),
    SignalState.SCORING: frozenset(
        {SignalState.SCORED, SignalState.CANCELLED, SignalState.FAILED}
    ),
    SignalState.SCORED: frozenset(
        {
            SignalState.RISK_PENDING,
            SignalState.WEAK_SIGNAL,
            SignalState.CANCELLED,
            SignalState.FAILED,
        }
    ),
    SignalState.RISK_PENDING: frozenset(
        {SignalState.RISK_APPROVED, SignalState.RISK_REJECTED, SignalState.FAILED}
    ),
    SignalState.RISK_APPROVED: frozenset({SignalState.FORWARDED, SignalState.FAILED}),
    SignalState.FORWARDED: frozenset(
        {
            SignalState.EXECUTED,
            SignalState.EXPIRED,
            SignalState.CANCELLED,
            SignalState.FAILED,
        }
    ),
    # Terminal states have no outgoing transitions.
    SignalState.EXECUTED: frozenset(),
    SignalState.EXPIRED: frozenset(),
    SignalState.CANCELLED: frozenset(),
    SignalState.RISK_REJECTED: frozenset(),
    SignalState.WEAK_SIGNAL: frozenset(),
    SignalState.FAILED: frozenset(),
}
