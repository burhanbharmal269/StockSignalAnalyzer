"""IKillSwitchRepository — domain port for system:kill_switch operations.

DESIGN INVARIANTS (Constraints 9 and 10):
  - The only Redis key is: system:kill_switch (Hash type, NO TTL).
  - KillSwitchService is the ONLY writer.  No other component may call activate()
    or deactivate() directly.
  - get_state() raises DataSourceUnavailableError when Redis is unreachable.
    Callers treat this as is_active=True (FAIL_CLOSED — same as kill switch armed).

FAIL_CLOSED on startup: the system must not process any signal before confirming
kill switch state.  See KillSwitchService.startup_check() (Constraint 20).

Reference: docs/14_KILL_SWITCH_DESIGN.md (authoritative kill switch design)
           docs/PHASE_13_IMPLEMENTATION_PLAN.md Section 4 (Redis key spec)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.risk.kill_switch_state import KillSwitchState


class IKillSwitchRepository(ABC):
    """Read/write access to the system:kill_switch Redis Hash.

    KillSwitchService is the sole component that calls activate() and deactivate().
    All other components call get_state() only.
    """

    @abstractmethod
    async def get_state(self) -> KillSwitchState:
        """Read the current kill switch state from Redis.

        Returns:
            A frozen KillSwitchState.

        Raises:
            DataSourceUnavailableError: On Redis ConnectionError or any read failure.
                                        source='kill_switch'
                                        FAIL_CLOSED: caller must treat as is_active=True.

        Note:
            If the key does not exist (first-ever startup), returns a default
            KillSwitchState(is_active=False, ...) with all optional fields None.
            A missing key is NOT an outage — it is a clean initialisation state.
        """

    @abstractmethod
    async def activate(
        self,
        reason: str,
        activated_by: str,
        trigger_source: str,
    ) -> None:
        """Write the activated state to system:kill_switch.

        Sets is_active='true' and records the activation metadata atomically via
        HSET.  MUST NOT set any TTL on the key.

        Args:
            reason:         Human-readable activation reason.
            activated_by:   One of: 'operator', 'risk_engine', 'dead_mans_switch', 'system'.
            trigger_source: Specific trigger condition (e.g. 'daily_loss_100pct').

        Raises:
            DataSourceUnavailableError: On Redis ConnectionError.
                                        source='kill_switch'
        """

    @abstractmethod
    async def deactivate(
        self,
        deactivated_by: str,
        note: str,
        override_loss_check: bool = False,
    ) -> None:
        """Write the deactivated state to system:kill_switch.

        Sets is_active='false' and records the deactivation metadata.
        MUST NOT set any TTL.

        Args:
            deactivated_by:     User ID or process name of the deactivating actor.
            note:               Operator-provided deactivation note.
            override_loss_check: True when the operator explicitly bypasses the
                                  post-recovery loss limit validation.

        Raises:
            DataSourceUnavailableError: On Redis ConnectionError.
                                        source='kill_switch'
        """
