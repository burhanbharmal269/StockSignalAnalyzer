"""IKillSwitchEventsRepository — domain port for kill_switch_events persistence.

kill_switch_events is INSERT-only.  The application DB user has INSERT permission
only on this table (enforced in migration 004_phase13, Constraint 6).

Implementations must NEVER provide update() or delete() methods.

Reference: docs/14_KILL_SWITCH_DESIGN.md (activation sequence step 5)
           docs/PHASE_13_IMPLEMENTATION_PLAN.md Section 1.5
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class IKillSwitchEventsRepository(ABC):
    """Append-only audit log for kill switch activations and deactivations."""

    @abstractmethod
    async def insert_event(
        self,
        event_type: str,
        triggered_by: str,
        trigger_source: str,
        reason: str,
        metadata: dict[str, object] | None,
        user_id: int | None,
    ) -> None:
        """Append a kill switch lifecycle event to the audit log.

        Args:
            event_type:     'ACTIVATED' or 'DEACTIVATED'.
            triggered_by:   Actor that triggered the event (user or system component).
            trigger_source: Specific trigger condition label from Doc 14.
            reason:         Human-readable reason string.
            metadata:       Optional JSON-serialisable supplementary data.
            user_id:        FK → users.id (None for automated triggers).

        Raises:
            RiskDecisionPersistenceError: On OperationalError or IntegrityError.
        """
