"""Unit tests for BrokerHealthService."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from core.application.services.broker.broker_health_service import BrokerHealthService
from core.domain.value_objects.broker_dtos import BrokerMargin
from core.domain.value_objects.broker_health import BrokerHealthReport, BrokerHealthStatus


def _broker(
    health_status: BrokerHealthStatus = BrokerHealthStatus.HEALTHY,
    health_raises: Exception | None = None,
    profile_raises: Exception | None = None,
    orders_raises: Exception | None = None,
    positions_raises: Exception | None = None,
    margin_raises: Exception | None = None,
) -> MagicMock:
    b = MagicMock()
    b.broker_name = "paper"

    report = BrokerHealthReport(
        broker_name="paper",
        status=health_status,
        latency_ms=1.0,
    )
    if health_raises:
        b.health_check = AsyncMock(side_effect=health_raises)
    else:
        b.health_check = AsyncMock(return_value=report)

    b.get_profile = AsyncMock(
        side_effect=profile_raises if profile_raises else None,
        return_value=MagicMock() if not profile_raises else None,
    )
    b.get_orders = AsyncMock(
        side_effect=orders_raises if orders_raises else None,
        return_value=[] if not orders_raises else None,
    )
    b.get_positions = AsyncMock(
        side_effect=positions_raises if positions_raises else None,
        return_value=[] if not positions_raises else None,
    )
    margin = BrokerMargin(
        available_cash=Decimal("80000"),
        used_margin=Decimal("20000"),
        total_margin=Decimal("100000"),
    )
    b.get_margin = AsyncMock(
        side_effect=margin_raises if margin_raises else None,
        return_value=margin if not margin_raises else None,
    )
    return b


def _session() -> MagicMock:
    return MagicMock()


class TestHealthCheckNoSession:
    async def test_healthy_with_no_session(self) -> None:
        svc = BrokerHealthService(_broker())
        report = await svc.check(session=None)
        assert report.status == BrokerHealthStatus.HEALTHY

    async def test_down_when_connectivity_fails_no_session(self) -> None:
        svc = BrokerHealthService(_broker(health_raises=Exception("connection refused")))
        report = await svc.check(session=None)
        assert report.status == BrokerHealthStatus.DOWN
        assert "connectivity" in report.error


class TestHealthCheckWithSession:
    async def test_healthy_all_probes_pass(self) -> None:
        svc = BrokerHealthService(_broker())
        report = await svc.check(session=_session())
        assert report.status == BrokerHealthStatus.HEALTHY
        assert report.details.get("connectivity") == "ok"
        assert report.details.get("auth") == "ok"
        assert report.details.get("orders") == "ok"
        assert report.details.get("positions") == "ok"
        assert report.details.get("margin") == "ok"

    async def test_down_when_connectivity_fails(self) -> None:
        svc = BrokerHealthService(_broker(health_raises=Exception("network error")))
        report = await svc.check(session=_session())
        assert report.status == BrokerHealthStatus.DOWN

    async def test_down_when_auth_fails(self) -> None:
        svc = BrokerHealthService(_broker(profile_raises=Exception("invalid token")))
        report = await svc.check(session=_session())
        assert report.status == BrokerHealthStatus.DOWN
        assert "auth" in report.error

    async def test_degraded_when_orders_fails(self) -> None:
        svc = BrokerHealthService(_broker(orders_raises=Exception("orders unavailable")))
        report = await svc.check(session=_session())
        assert report.status == BrokerHealthStatus.DEGRADED
        assert report.details.get("orders") == "failed"

    async def test_degraded_when_positions_fails(self) -> None:
        svc = BrokerHealthService(_broker(positions_raises=Exception("positions unavailable")))
        report = await svc.check(session=_session())
        assert report.status == BrokerHealthStatus.DEGRADED
        assert report.details.get("positions") == "failed"

    async def test_degraded_when_margin_fails(self) -> None:
        svc = BrokerHealthService(_broker(margin_raises=Exception("margin unavailable")))
        report = await svc.check(session=_session())
        assert report.status == BrokerHealthStatus.DEGRADED
        assert report.details.get("margin") == "failed"

    async def test_broker_name_in_report(self) -> None:
        svc = BrokerHealthService(_broker())
        report = await svc.check(session=_session())
        assert report.broker_name == "paper"

    async def test_latency_ms_is_non_negative(self) -> None:
        svc = BrokerHealthService(_broker())
        report = await svc.check(session=_session())
        assert report.latency_ms >= 0
