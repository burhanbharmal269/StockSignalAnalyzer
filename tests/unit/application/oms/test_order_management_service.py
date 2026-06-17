"""Unit tests — OrderManagementService.

Coverage:
  - Signal TTL expiration
  - Idempotency block (duplicate signal_id)
  - Kill switch active → rejection
  - Rate limit exceeded
  - Happy path: order created + persisted + event published
  - Persistence failure raises OrderPersistenceError
  - LIMIT order selected for high-premium options
  - MARKET order selected for low-premium options
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.oms.order_management_service import OrderManagementService
from core.domain.enums.order_state import OrderState
from core.domain.enums.order_type import OrderType
from core.domain.exceptions.order import (
    KillSwitchActiveError,
    OrderPersistenceError,
    OrderRateLimitError,
    SignalExpiredError,
)
from core.domain.risk.kill_switch_state import KillSwitchState
from core.domain.value_objects.order_request import OrderRequest
from core.infrastructure.config.oms_config import OmsConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ks_state(active: bool) -> KillSwitchState:
    if active:
        return KillSwitchState(
            is_active=True,
            activated_at=datetime.now(UTC),
            activated_by="system",
            activation_reason="test",
            deactivated_at=None,
            deactivated_by=None,
            deactivation_note=None,
        )
    return KillSwitchState(
        is_active=False,
        activated_at=None,
        activated_by=None,
        activation_reason=None,
        deactivated_at=None,
        deactivated_by=None,
        deactivation_note=None,
    )


def _make_request(
    *,
    expired: bool = False,
    direction: str = "LONG",
    option_premium: Decimal | None = Decimal("100"),
) -> OrderRequest:
    now = datetime.now(UTC)
    valid_until = now - timedelta(minutes=1) if expired else now + timedelta(minutes=5)
    return OrderRequest(
        signal_id=uuid.uuid4(),
        instrument_token=12345,
        underlying="NIFTY",
        tradingsymbol="NIFTY24JAN18000CE",
        exchange="NFO",
        direction=direction,
        strategy_type="DIRECTIONAL",
        regime="Trend",
        position_size_lots=1,
        lot_size=50,
        entry_price=Decimal("200"),
        stop_loss_price=Decimal("180"),
        target_1_price=Decimal("230"),
        target_2_price=Decimal("250"),
        option_premium=option_premium,
        risk_decision_id=42,
        adjusted_score=0.75,
        final_confidence=0.80,
        valid_until=valid_until,
        trading_mode="LIVE",
    )


@pytest.fixture
def mock_order_repo():
    repo = AsyncMock()
    repo.save = AsyncMock()
    return repo


@pytest.fixture
def mock_order_cache():
    cache = AsyncMock()
    cache.set_idempotency_key = AsyncMock(return_value=True)  # new by default
    cache.get_idempotency_order_id = AsyncMock(return_value=None)
    return cache


@pytest.fixture
def mock_kill_switch():
    ks = AsyncMock()
    ks.get_state = AsyncMock(return_value=_make_ks_state(False))
    return ks


@pytest.fixture
def mock_event_bus():
    bus = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def config():
    cfg = MagicMock(spec=OmsConfig)
    cfg.max_orders_per_minute = 10
    cfg.idempotency_ttl_seconds = 300
    cfg.idempotency_key = lambda s: f"oms:idem:{s}"
    cfg.order_cache_key = lambda s: f"oms:order:{s}"
    cfg.position_cache_key = lambda s: f"oms:position:{s}"
    cfg.order_type = MagicMock()
    cfg.order_type.default = "MARKET"
    cfg.order_type.limit_threshold_premium = Decimal("500")
    cfg.order_type.limit_buffer_pct = 0.001
    return cfg


@pytest.fixture
def svc(mock_order_repo, mock_order_cache, mock_kill_switch, mock_event_bus, config):
    return OrderManagementService(
        order_repository=mock_order_repo,
        order_cache=mock_order_cache,
        kill_switch_repository=mock_kill_switch,
        event_bus=mock_event_bus,
        config=config,
    )


# ---------------------------------------------------------------------------
# Signal TTL expiration
# ---------------------------------------------------------------------------

class TestSignalTtlExpiration:
    @pytest.mark.asyncio
    async def test_expired_signal_raises(self, svc):
        req = _make_request(expired=True)
        with pytest.raises(SignalExpiredError):
            await svc.process(req)

    @pytest.mark.asyncio
    async def test_expired_signal_publishes_ttl_event(self, svc, mock_event_bus):
        req = _make_request(expired=True)
        with pytest.raises(SignalExpiredError):
            await svc.process(req)
        mock_event_bus.publish.assert_called_once()
        event = mock_event_bus.publish.call_args[0][0]
        assert type(event).__name__ == "OrderTtlExpired"

    @pytest.mark.asyncio
    async def test_expired_signal_does_not_persist(self, svc, mock_order_repo):
        req = _make_request(expired=True)
        with pytest.raises(SignalExpiredError):
            await svc.process(req)
        mock_order_repo.save.assert_not_called()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_signal_returns_is_duplicate(self, svc, mock_order_cache):
        mock_order_cache.set_idempotency_key = AsyncMock(return_value=False)
        existing_id = uuid.uuid4()
        mock_order_cache.get_idempotency_order_id = AsyncMock(return_value=existing_id)

        req = _make_request()
        result = await svc.process(req)

        assert result.is_duplicate is True
        assert result.accepted is False

    @pytest.mark.asyncio
    async def test_duplicate_does_not_create_order(self, svc, mock_order_cache, mock_order_repo):
        mock_order_cache.set_idempotency_key = AsyncMock(return_value=False)
        mock_order_cache.get_idempotency_order_id = AsyncMock(return_value=uuid.uuid4())

        await svc.process(_make_request())
        mock_order_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_publishes_idempotency_blocked_event(
        self, svc, mock_order_cache, mock_event_bus
    ):
        mock_order_cache.set_idempotency_key = AsyncMock(return_value=False)
        mock_order_cache.get_idempotency_order_id = AsyncMock(return_value=uuid.uuid4())

        await svc.process(_make_request())
        event = mock_event_bus.publish.call_args[0][0]
        assert type(event).__name__ == "OrderIdempotencyBlocked"


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_active_kill_switch_raises(self, svc, mock_kill_switch):
        mock_kill_switch.get_state = AsyncMock(return_value=_make_ks_state(True))
        with pytest.raises(KillSwitchActiveError):
            await svc.process(_make_request())

    @pytest.mark.asyncio
    async def test_active_kill_switch_does_not_persist(
        self, svc, mock_kill_switch, mock_order_repo
    ):
        mock_kill_switch.get_state = AsyncMock(return_value=_make_ks_state(True))
        with pytest.raises(KillSwitchActiveError):
            await svc.process(_make_request())
        mock_order_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_active_kill_switch_publishes_event(
        self, svc, mock_kill_switch, mock_event_bus
    ):
        mock_kill_switch.get_state = AsyncMock(return_value=_make_ks_state(True))
        with pytest.raises(KillSwitchActiveError):
            await svc.process(_make_request())
        published_types = [type(c[0][0]).__name__ for c in mock_event_bus.publish.call_args_list]
        assert "OrderKillSwitchBlocked" in published_types


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------

class TestRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_raises(self, svc, mock_order_repo):
        # Inject 10 fake recent timestamps
        from datetime import UTC
        svc._recent_order_times = [datetime.now(UTC)] * 10

        with pytest.raises(OrderRateLimitError):
            await svc.process(_make_request())

    @pytest.mark.asyncio
    async def test_rate_limit_does_not_count_old_timestamps(self, svc, mock_order_repo):
        # Old timestamps outside the 60-second window should not count
        old = datetime.now(UTC) - timedelta(seconds=120)
        svc._recent_order_times = [old] * 10  # All old

        result = await svc.process(_make_request())
        assert result.accepted is True


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_accepted_result(self, svc):
        result = await svc.process(_make_request())
        assert result.accepted is True
        assert result.order_id is not None
        assert result.is_duplicate is False

    @pytest.mark.asyncio
    async def test_order_persisted_before_event(self, svc, mock_order_repo, mock_event_bus):
        call_order = []
        mock_order_repo.save = AsyncMock(side_effect=lambda o: call_order.append("save"))
        mock_event_bus.publish = AsyncMock(side_effect=lambda e: call_order.append("publish"))

        await svc.process(_make_request())

        assert call_order[0] == "save"
        assert "publish" in call_order

    @pytest.mark.asyncio
    async def test_order_created_event_published(self, svc, mock_event_bus):
        await svc.process(_make_request())
        published_types = [type(c[0][0]).__name__ for c in mock_event_bus.publish.call_args_list]
        assert "OrderCreated" in published_types

    @pytest.mark.asyncio
    async def test_market_order_for_low_premium(self, svc, mock_order_repo):
        # premium 100 < threshold 500 → MARKET
        req = _make_request(option_premium=Decimal("100"))
        await svc.process(req)
        saved_order = mock_order_repo.save.call_args[0][0]
        assert saved_order.order_type == OrderType.MARKET

    @pytest.mark.asyncio
    async def test_limit_order_for_high_premium(self, svc, mock_order_repo):
        # premium 600 > threshold 500 → LIMIT
        req = _make_request(option_premium=Decimal("600"))
        await svc.process(req)
        saved_order = mock_order_repo.save.call_args[0][0]
        assert saved_order.order_type == OrderType.LIMIT

    @pytest.mark.asyncio
    async def test_sell_transaction_for_short_direction(self, svc, mock_order_repo):
        from core.domain.enums.transaction_type import TransactionType
        req = _make_request(direction="SHORT")
        await svc.process(req)
        saved_order = mock_order_repo.save.call_args[0][0]
        assert saved_order.transaction_type == TransactionType.SELL

    @pytest.mark.asyncio
    async def test_result_state_is_pending(self, svc):
        result = await svc.process(_make_request())
        assert result.state == OrderState.PENDING


# ---------------------------------------------------------------------------
# Persistence failure
# ---------------------------------------------------------------------------

class TestPersistenceFailure:
    @pytest.mark.asyncio
    async def test_db_failure_raises_order_persistence_error(
        self, svc, mock_order_repo
    ):
        mock_order_repo.save = AsyncMock(side_effect=RuntimeError("DB down"))
        with pytest.raises(OrderPersistenceError):
            await svc.process(_make_request())

    @pytest.mark.asyncio
    async def test_event_bus_failure_does_not_propagate(
        self, svc, mock_event_bus
    ):
        mock_event_bus.publish = AsyncMock(side_effect=RuntimeError("bus down"))
        # Should not raise — event bus failures are fail-open
        result = await svc.process(_make_request())
        assert result.accepted is True
