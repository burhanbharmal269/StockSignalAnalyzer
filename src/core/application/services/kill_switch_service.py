"""KillSwitchService — application service for kill switch lifecycle management.

Idempotency (AD-D-01):
  - activate():    reads state first; returns immediately if already active.
  - deactivate():  reads state first; returns immediately if already inactive.

Activation order (AD-D-01 §Activation Order):
  1. Redis HSET  (system:kill_switch is_active="true")
  2. DB INSERT   (kill_switch_events)
  3. Event Publish (KillSwitchActivated)

If step 2 (DB INSERT) fails: log CRITICAL and return. Kill switch is still
active in Redis. Event is NOT published when audit insert fails.

startup_check(): validates kill switch state at application startup.
If the state read fails (Redis unavailable), raises DataSourceUnavailableError
so the application lifespan refuses to start (FAIL_CLOSED, Constraint 20).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from core.domain.events.risk_events import KillSwitchActivated, KillSwitchDeactivated
from core.domain.exceptions.risk import RiskDecisionPersistenceError
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_kill_switch_events_repository import IKillSwitchEventsRepository
from core.domain.interfaces.i_kill_switch_repository import IKillSwitchRepository

_log = logging.getLogger(__name__)


class KillSwitchService:

    def __init__(
        self,
        kill_switch_repo: IKillSwitchRepository,
        kill_switch_events_repo: IKillSwitchEventsRepository,
        event_bus: IEventBus,
    ) -> None:
        self._ks_repo = kill_switch_repo
        self._ks_events_repo = kill_switch_events_repo
        self._event_bus = event_bus

    async def startup_check(self) -> None:
        """Confirm kill switch state is readable on startup.

        Raises:
            DataSourceUnavailableError: if Redis is unreachable (FAIL_CLOSED).
        """
        state = await self._ks_repo.get_state()
        if state.is_active:
            _log.warning("startup: kill switch is ACTIVE — trading blocked until deactivated")
        else:
            _log.info("startup: kill switch state confirmed inactive")

    async def activate(
        self,
        reason: str,
        activated_by: str,
        trigger_source: str,
    ) -> None:
        """Activate the kill switch.  Idempotent — no-op if already active (AD-D-01)."""
        current = await self._ks_repo.get_state()
        if current.is_active:
            return

        # Step 1: Redis HSET
        await self._ks_repo.activate(
            reason=reason,
            activated_by=activated_by,
            trigger_source=trigger_source,
        )

        # Step 2: DB INSERT (audit)
        try:
            await self._ks_events_repo.insert_event(
                event_type="ACTIVATED",
                triggered_by=activated_by,
                trigger_source=trigger_source,
                reason=reason,
                metadata=None,
                user_id=None,
            )
        except RiskDecisionPersistenceError:
            _log.critical(
                "kill_switch_audit_insert_failed activated_by=%s trigger=%s reason=%s",
                activated_by,
                trigger_source,
                reason,
                exc_info=True,
            )
            # Kill switch IS active in Redis. Do not publish — no audit record.
            return

        # Step 3: Event publish
        now = datetime.now(UTC)
        await self._event_bus.publish(
            KillSwitchActivated(
                reason=reason,
                activated_by=activated_by,
                trigger_source=trigger_source,
                activated_at=now,
            )
        )
        _log.critical(
            "kill_switch_activated reason=%s activated_by=%s trigger=%s",
            reason,
            activated_by,
            trigger_source,
        )

    async def deactivate(
        self,
        deactivated_by: str,
        note: str,
        override_loss_check: bool = False,
    ) -> None:
        """Deactivate the kill switch.  Idempotent — no-op if already inactive."""
        current = await self._ks_repo.get_state()
        if not current.is_active:
            return

        # Step 1: Redis HSET
        await self._ks_repo.deactivate(
            deactivated_by=deactivated_by,
            note=note,
            override_loss_check=override_loss_check,
        )

        # Step 2: DB INSERT (audit)
        try:
            await self._ks_events_repo.insert_event(
                event_type="DEACTIVATED",
                triggered_by=deactivated_by,
                trigger_source="manual",
                reason=note,
                metadata={"override_loss_check": override_loss_check},
                user_id=None,
            )
        except RiskDecisionPersistenceError:
            _log.critical(
                "kill_switch_deactivation_audit_insert_failed deactivated_by=%s",
                deactivated_by,
                exc_info=True,
            )
            return

        # Step 3: Event publish
        now = datetime.now(UTC)
        await self._event_bus.publish(
            KillSwitchDeactivated(
                deactivated_by=deactivated_by,
                deactivated_at=now,
                deactivation_note=note,
                override_loss_check=override_loss_check,
            )
        )
        _log.warning(
            "kill_switch_deactivated deactivated_by=%s override=%s",
            deactivated_by,
            override_loss_check,
        )
