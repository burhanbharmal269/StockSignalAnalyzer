"""BrokerReconciliationService — application-level coordinator for reconciliation.

Sits above the OMS ReconciliationService and manages the full reconciliation cycle:
  1. Get the active broker session from the session repository.
  2. Validate the session — refresh if expired.
  3. Delegate to OMS ReconciliationService.run(session).
  4. Handle RogueOrderDetectedError (already activates kill switch inside OMS service).
  5. Log the result.

Designed to be called by a background scheduler (e.g. every 60 seconds).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.services.oms.reconciliation_service import (
        ReconciliationResult,
        ReconciliationService,
    )
    from core.domain.interfaces.i_broker_session_repository import IBrokerSessionRepository
    from core.infrastructure.broker.broker_session_manager import BrokerSessionManager

_log = logging.getLogger(__name__)


class BrokerReconciliationService:
    """Schedules and coordinates broker vs OMS reconciliation runs."""

    def __init__(
        self,
        session_repository: IBrokerSessionRepository,
        oms_reconciliation_service: ReconciliationService,
        session_manager: BrokerSessionManager,
        broker_name: str,
    ) -> None:
        self._session_repo = session_repository
        self._reconciliation = oms_reconciliation_service
        self._session_manager = session_manager
        self._broker_name = broker_name

    async def run(self) -> ReconciliationResult | None:
        """Execute one reconciliation pass.

        Returns the ReconciliationResult, or None if no active session found.
        """
        session = await self._session_repo.get_active(self._broker_name)
        if session is None:
            _log.warning(
                "BrokerReconciliationService.run: no active session for broker=%s — skipping",
                self._broker_name,
            )
            return None

        if session.is_expired():
            _log.warning(
                "BrokerReconciliationService.run: session expired broker=%s — deactivating",
                self._broker_name,
            )
            await self._session_manager.terminate_session(session)
            return None

        try:
            result = await self._reconciliation.run(session=session)
        except Exception:
            _log.exception(
                "BrokerReconciliationService.run: reconciliation failed broker=%s",
                self._broker_name,
            )
            return None

        _log.info(
            "BrokerReconciliationService.run complete broker=%s orders=%d positions=%d "
            "discrepancies=%d rogue=%d",
            self._broker_name,
            result.orders_checked,
            result.positions_checked,
            result.discrepancy_count,
            result.rogue_count,
        )
        return result
