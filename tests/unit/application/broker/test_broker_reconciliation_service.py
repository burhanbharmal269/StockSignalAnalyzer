"""Unit tests for BrokerReconciliationService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from core.application.services.broker.broker_reconciliation_service import (
    BrokerReconciliationService,
)
from core.domain.entities.broker_session import BrokerSession


def _session(expired: bool = False, active: bool = True) -> BrokerSession:
    expires_at = (
        datetime.now(UTC) - timedelta(hours=1)
        if expired
        else datetime(2099, 12, 31, tzinfo=UTC)
    )
    s = BrokerSession.create(
        broker_name="paper",
        api_key="key",
        encrypted_access_token="enc",
        expires_at=expires_at,
    )
    if not active:
        s.deactivate()
    return s


def _make_service(
    active_session: BrokerSession | None = None,
    reconciliation_result: MagicMock | None = None,
    reconciliation_raises: Exception | None = None,
) -> tuple[BrokerReconciliationService, MagicMock, MagicMock, MagicMock]:
    session_repo = MagicMock()
    session_repo.get_active = AsyncMock(return_value=active_session)

    result = reconciliation_result or MagicMock(
        orders_checked=5,
        positions_checked=2,
        discrepancy_count=0,
        rogue_count=0,
    )
    oms_reconciliation = MagicMock()
    if reconciliation_raises:
        oms_reconciliation.run = AsyncMock(side_effect=reconciliation_raises)
    else:
        oms_reconciliation.run = AsyncMock(return_value=result)

    session_manager = MagicMock()
    session_manager.terminate_session = AsyncMock()

    svc = BrokerReconciliationService(
        session_repository=session_repo,
        oms_reconciliation_service=oms_reconciliation,
        session_manager=session_manager,
        broker_name="paper",
    )
    return svc, session_repo, oms_reconciliation, session_manager


class TestBrokerReconciliationService:
    async def test_returns_none_when_no_active_session(self) -> None:
        svc, _, _, _ = _make_service(active_session=None)
        result = await svc.run()
        assert result is None

    async def test_calls_oms_reconciliation_with_session(self) -> None:
        s = _session()
        svc, _, oms, _ = _make_service(active_session=s)
        await svc.run()
        oms.run.assert_called_once_with(session=s)

    async def test_returns_reconciliation_result(self) -> None:
        s = _session()
        expected = MagicMock(
            orders_checked=10, positions_checked=3, discrepancy_count=1, rogue_count=0
        )
        svc, _, _, _ = _make_service(active_session=s, reconciliation_result=expected)
        result = await svc.run()
        assert result is expected

    async def test_terminates_expired_session_returns_none(self) -> None:
        s = _session(expired=True)
        svc, _, oms, session_manager = _make_service(active_session=s)
        result = await svc.run()
        assert result is None
        session_manager.terminate_session.assert_called_once_with(s)
        oms.run.assert_not_called()

    async def test_returns_none_when_reconciliation_raises(self) -> None:
        s = _session()
        svc, _, _, _ = _make_service(
            active_session=s,
            reconciliation_raises=Exception("unexpected error"),
        )
        result = await svc.run()
        assert result is None  # swallowed, logged
