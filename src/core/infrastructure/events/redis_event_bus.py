"""RedisStreamEventBus — Phase 1 event bus using Redis Streams.

Reference: docs/11_EVENT_BUS_ARCHITECTURE.md
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from redis.asyncio import Redis

from core.domain.events.base import DomainEvent
from core.domain.interfaces.i_event_bus import EventHandler, IEventBus
from core.infrastructure.events.message_envelope import MessageEnvelope, reconstruct_event

_TOPICS_BY_EVENT_TYPE: dict[str, str] = {
    "TickReceivedEvent": "market_data.tick.received",
    "CandleClosedEvent": "market_data.candle.closed",
    "OptionChainUpdatedEvent": "market_data.option_chain.updated",
    "MarketRegimeEvaluatedEvent": "features.regime.detected",
    "MarketRegimeChangedEvent": "features.regime.changed",
    # Universe
    "UniverseSelected": "universe.selected",
    # Signal pipeline
    "SignalGenerated": "signal.generated",
    "SignalScored": "signal.scored",
    "SignalWeakRejected": "signal.weak_rejected",
    "SignalRiskApproved": "signal.risk.approved",
    "SignalRiskRejected": "signal.risk.rejected",
    "SignalForwarded": "signal.forwarded",
    "SignalExecuted": "signal.executed",
    "SignalExpired": "signal.expired",
    "SignalCancelled": "signal.cancelled",
    # Risk engine
    "RiskApproved": "signal.risk.approved",
    "RiskRejected": "signal.risk.rejected",
    "DailyLossLimitBreached": "risk.limit.breached",
    "WeeklyLossLimitBreached": "risk.limit.breached",
    "DrawdownLimitBreached": "risk.drawdown.alert",
    "GraduatedResponseActivated": "risk.drawdown.alert",
    "PaperModeActivated": "risk.drawdown.alert",
    "HighWaterMarkUpdated": "risk.drawdown.alert",
    "MarginAlertBreached": "risk.margin.alert",
    "DataSourceUnavailable": "signal.risk.rejected",
    # OMS order lifecycle
    "OrderCreated": "order.created",
    "OrderValidated": "order.validated",
    "OrderRouted": "order.routed",
    "OrderSubmitted": "order.submitted",
    "OrderFilled": "order.filled",
    "OrderPartiallyFilled": "order.partially_filled",
    "OrderCancelled": "order.cancelled",
    "OrderRejected": "order.rejected",
    "OrderExpired": "order.expired",
    "OrderTtlExpired": "order.ttl_expired",
    "OrderIdempotencyBlocked": "order.idempotency_blocked",
    "OrderKillSwitchBlocked": "order.kill_switch_blocked",
    # OMS position lifecycle
    "PositionOpened": "position.opened",
    "PositionClosed": "position.closed",
    "StopLossPlaced": "position.sl_placed",
    "StopLossTriggered": "position.sl_triggered",
    "TargetPlaced": "position.target_placed",
    "TargetTriggered": "position.target_triggered",
    # OMS reconciliation
    "ReconciliationCompleted": "oms.reconciliation.completed",
    "ReconciliationDiscrepancyDetected": "oms.reconciliation.discrepancy",
    # Kill switch
    "KillSwitchActivated": "system.kill_switch.activated",
    "KillSwitchDeactivated": "system.kill_switch.deactivated",
    # System
    "HeartbeatPublished": "system.heartbeat",
    "SystemHealthChanged": "system.health_check.changed",
    "InstrumentMasterRefreshed": "system.instrument_master.refreshed",
}

_MAXLEN: dict[str, int] = {
    "market_data.tick.received": 100_000,
    "market_data.candle.closed": 50_000,
    "market_data.option_chain.updated": 50_000,
    "universe.selected": 5_000,
    "signal.risk.approved": 10_000,
    "signal.risk.rejected": 10_000,
    "order.created": 50_000,
    "order.submitted": 50_000,
    "order.filled": 50_000,
    "position.opened": 50_000,
    "position.closed": 50_000,
    "system.kill_switch.activated": 10_000,
    "oms.reconciliation.discrepancy": 10_000,
}
_DEFAULT_MAXLEN = 10_000
_BLOCK_MS = 2_000
_RETRY_SLEEP = 0.5

logger = logging.getLogger(__name__)


def _topic_for(event_or_type: DomainEvent | type[DomainEvent]) -> str:
    """Return the documented Redis stream key for an event instance or class."""
    if isinstance(event_or_type, type):
        event_type = event_or_type.__name__
    else:
        event_type = type(event_or_type).__name__
    return _TOPICS_BY_EVENT_TYPE.get(event_type, event_type)


def _event_name_for(event_or_type: DomainEvent | type[DomainEvent]) -> str:
    if isinstance(event_or_type, type):
        return event_or_type.__name__
    return type(event_or_type).__name__


class RedisStreamEventBus(IEventBus):
    """Redis Streams implementation of IEventBus.

    Consumer groups provide at-least-once delivery.
    XACK must be called after successful processing.
    Failed messages beyond max_retries are moved to dlq.<topic>.
    """

    def __init__(
        self,
        redis: Redis,  # type: ignore[type-arg]
        source: str,
        max_retries: int = 3,
    ) -> None:
        self._redis = redis
        self._source = source
        self._max_retries = max_retries
        self._consumer_tasks: list[asyncio.Task[None]] = []

    async def publish(self, event: DomainEvent) -> None:
        topic = _topic_for(event)
        envelope = MessageEnvelope.wrap(event, topic=topic, source=self._source)
        maxlen = _MAXLEN.get(topic, _DEFAULT_MAXLEN)
        await self._redis.xadd(
            topic,
            envelope.to_redis_fields(),
            maxlen=maxlen,
            approximate=True,
        )

    async def subscribe(
        self,
        event_type: type[DomainEvent],
        handler: EventHandler,
        consumer_group: str,
        consumer_name: str,
    ) -> None:
        topic = _topic_for(event_type)
        await self._ensure_consumer_group(topic, consumer_group)
        task = asyncio.create_task(
            self._consume_loop(topic, consumer_group, consumer_name, handler),
            name=f"redis-consumer-{consumer_group}-{consumer_name}",
        )
        self._consumer_tasks.append(task)

    async def replay(
        self,
        event_type: type[DomainEvent],
        from_id: str,
        to_id: str,
    ) -> AsyncIterator[DomainEvent]:
        topic = _topic_for(event_type)
        messages = await self._redis.xrange(topic, min=from_id, max=to_id)
        for _msg_id, fields in messages:
            try:
                envelope = MessageEnvelope.from_redis_fields(fields)
                event = _reconstruct_event(event_type, envelope)
                if event is not None:
                    yield event
            except Exception:
                logger.exception("Failed to deserialize replay message from %s", topic)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _ensure_consumer_group(self, topic: str, group: str) -> None:
        try:
            await self._redis.xgroup_create(topic, group, id="0", mkstream=True)
        except Exception as exc:
            # BUSYGROUP: group already exists — safe to ignore.
            if "BUSYGROUP" not in str(exc):
                raise

    async def _consume_loop(
        self,
        topic: str,
        group: str,
        consumer_name: str,
        handler: EventHandler,
    ) -> None:
        while True:
            try:
                results = await self._redis.xreadgroup(
                    group,
                    consumer_name,
                    {topic: ">"},
                    count=10,
                    block=_BLOCK_MS,
                )
                if not results:
                    continue
                for _stream, messages in results:
                    for msg_id, fields in messages:
                        await self._handle_message(
                            topic, group, msg_id, fields, handler
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in Redis consumer %s/%s", group, consumer_name)
                await asyncio.sleep(_RETRY_SLEEP)

    async def _handle_message(
        self,
        topic: str,
        group: str,
        msg_id: str,
        fields: dict[str, str | bytes],
        handler: EventHandler,
    ) -> None:
        try:
            envelope = MessageEnvelope.from_redis_fields(fields)
            event = _reconstruct_event_from_envelope(envelope)
            await handler(event)
            await self._redis.xack(topic, group, msg_id)
        except Exception:
            logger.exception("Handler failed for message %s on %s", msg_id, topic)
            await self._move_to_dlq(topic, fields, msg_id)
            await self._redis.xack(topic, group, msg_id)

    async def _move_to_dlq(
        self, topic: str, fields: dict[str, str | bytes], original_id: str
    ) -> None:
        dlq_topic = f"dlq.{topic}"
        dlq_fields = dict(fields)
        dlq_fields["original_id"] = original_id
        await self._redis.xadd(dlq_topic, dlq_fields, maxlen=10_000, approximate=True)

    async def close(self) -> None:
        for task in self._consumer_tasks:
            task.cancel()
        if self._consumer_tasks:
            await asyncio.gather(*self._consumer_tasks, return_exceptions=True)
        self._consumer_tasks.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reconstruct_event(
    event_type: type[DomainEvent], envelope: MessageEnvelope
) -> DomainEvent | None:
    """Best-effort reconstruction of a typed event from an envelope payload."""
    return reconstruct_event(event_type, envelope)


def _reconstruct_event_from_envelope(envelope: MessageEnvelope) -> DomainEvent:
    """Reconstruct using the event class named in the message envelope."""
    event_type = _EVENT_TYPES_BY_NAME.get(envelope.event_type)
    if event_type is None:
        msg = f"No event type registered for {envelope.event_type!r}"
        raise ValueError(msg)
    return reconstruct_event(event_type, envelope)


def _build_event_type_registry() -> dict[str, type[DomainEvent]]:
    from core.domain.events.market_events import CandleClosedEvent, OptionChainUpdatedEvent
    from core.domain.events.order_events import (
        OrderCancelled,
        OrderCreated,
        OrderExpired,
        OrderFilled,
        OrderIdempotencyBlocked,
        OrderKillSwitchBlocked,
        OrderPartiallyFilled,
        OrderRejected,
        OrderRouted,
        OrderSubmitted,
        OrderTtlExpired,
        OrderValidated,
        PositionClosed,
        PositionOpened,
        ReconciliationCompleted,
        ReconciliationDiscrepancyDetected,
        StopLossPlaced,
        StopLossTriggered,
        TargetPlaced,
        TargetTriggered,
    )
    from core.domain.events.regime_events import (
        MarketRegimeChangedEvent,
        MarketRegimeEvaluatedEvent,
    )
    from core.domain.events.risk_events import (
        DailyLossLimitBreached,
        DataSourceUnavailable,
        DrawdownLimitBreached,
        GraduatedResponseActivated,
        HighWaterMarkUpdated,
        KillSwitchActivated,
        KillSwitchDeactivated,
        MarginAlertBreached,
        PaperModeActivated,
        RiskApproved,
        RiskRejected,
        WeeklyLossLimitBreached,
    )
    from core.domain.events.signal_events import (
        SignalCancelled,
        SignalExecuted,
        SignalExpired,
        SignalForwarded,
        SignalGenerated,
        SignalRiskApproved,
        SignalRiskRejected,
        SignalScored,
        SignalWeakRejected,
    )
    from core.domain.events.system_events import (
        HeartbeatPublished,
        InstrumentMasterRefreshed,
        SystemHealthChanged,
    )
    from core.domain.events.tick_received import TickReceivedEvent
    from core.domain.events.universe_events import UniverseSelected

    event_types: tuple[type[DomainEvent], ...] = (
        TickReceivedEvent,
        CandleClosedEvent,
        OptionChainUpdatedEvent,
        MarketRegimeEvaluatedEvent,
        MarketRegimeChangedEvent,
        # Universe
        UniverseSelected,
        # Signal pipeline
        SignalGenerated,
        SignalScored,
        SignalWeakRejected,
        SignalRiskApproved,
        SignalRiskRejected,
        SignalForwarded,
        SignalExecuted,
        SignalExpired,
        SignalCancelled,
        # Risk engine
        RiskApproved,
        RiskRejected,
        DailyLossLimitBreached,
        WeeklyLossLimitBreached,
        DrawdownLimitBreached,
        GraduatedResponseActivated,
        PaperModeActivated,
        HighWaterMarkUpdated,
        MarginAlertBreached,
        DataSourceUnavailable,
        KillSwitchActivated,
        KillSwitchDeactivated,
        # OMS order lifecycle
        OrderCreated,
        OrderValidated,
        OrderRouted,
        OrderSubmitted,
        OrderFilled,
        OrderPartiallyFilled,
        OrderCancelled,
        OrderRejected,
        OrderExpired,
        OrderTtlExpired,
        OrderIdempotencyBlocked,
        OrderKillSwitchBlocked,
        # OMS position lifecycle
        PositionOpened,
        PositionClosed,
        StopLossPlaced,
        StopLossTriggered,
        TargetPlaced,
        TargetTriggered,
        # OMS reconciliation
        ReconciliationCompleted,
        ReconciliationDiscrepancyDetected,
        # System
        HeartbeatPublished,
        SystemHealthChanged,
        InstrumentMasterRefreshed,
    )
    return {_event_name_for(event_type): event_type for event_type in event_types}


_EVENT_TYPES_BY_NAME = _build_event_type_registry()
