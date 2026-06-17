"""MarketRegimeService — stateful application-layer orchestrator.

Responsibilities:
 1. Subscribe to CandleClosedEvent (15-min bars only).
 2. Cache FeatureSnapshot per (instrument_token, timeframe).
 3. On candle close: evaluate regime, apply smoothing, persist, publish events.
 4. Implement IMarketRegimeEngine so it is swappable behind the interface.

Published events:
  MarketRegimeEvaluatedEvent → every bar
  MarketRegimeChangedEvent   → only on primary regime transition

This service is FORBIDDEN from: Order Placement, Risk Management,
Position Sizing, Final Trade Decision, Stoploss Calculation, Margin Decisions.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from core.domain.events.regime_events import (
    MarketRegimeChangedEvent,
    MarketRegimeEvaluatedEvent,
)
from core.domain.interfaces.i_market_regime_engine import IMarketRegimeEngine
from core.domain.value_objects.regime_snapshot import RegimeSnapshot
from core.infrastructure.logging.setup import get_logger

if TYPE_CHECKING:
    from core.application.use_cases.regime_evaluation_use_case import (
        RegimeEvaluationUseCase,
    )
    from core.domain.events.market_events import CandleClosedEvent
    from core.domain.interfaces.i_event_bus import IEventBus
    from core.domain.interfaces.i_regime_repository import IRegimeRepository
    from core.domain.regime.regime_smoother import RegimeSmoother
    from core.domain.value_objects.feature_snapshot import FeatureSnapshot

logger = get_logger(__name__)

_TARGET_TIMEFRAME = "15m"


class MarketRegimeService(IMarketRegimeEngine):
    """Stateful regime engine orchestrator.

    Inject via DI container — one instance per application lifetime.
    """

    def __init__(
        self,
        evaluation_use_case: RegimeEvaluationUseCase,
        smoother: RegimeSmoother,
        regime_repository: IRegimeRepository,
        event_bus: IEventBus,
    ) -> None:
        self._use_case = evaluation_use_case
        self._smoother = smoother
        self._repository = regime_repository
        self._bus = event_bus
        self._feature_cache: dict[tuple[int, str], FeatureSnapshot] = {}

    async def start(self) -> None:
        """Subscribe to candle close events."""
        from core.domain.events.market_events import CandleClosedEvent

        await self._bus.subscribe(
            event_type=CandleClosedEvent,
            handler=self._on_candle_closed,
            consumer_group="regime_engine",
            consumer_name="regime_engine_1",
        )
        logger.info("regime_engine.started")

    async def stop(self) -> None:
        logger.info("regime_engine.stopped")

    # ------------------------------------------------------------------
    # IMarketRegimeEngine
    # ------------------------------------------------------------------

    async def update_features(self, snapshot: FeatureSnapshot) -> None:
        """Cache fresh feature snapshot. Called by Feature Engineering pipeline."""
        key = (snapshot.instrument_token, snapshot.timeframe)
        self._feature_cache[key] = snapshot
        logger.debug(
            "regime_engine.features_updated",
            token=snapshot.instrument_token,
            timeframe=snapshot.timeframe,
        )

    async def evaluate(self, snapshot: FeatureSnapshot) -> RegimeSnapshot:
        """Direct evaluation — bypasses candle-close subscription.

        Useful for on-demand regime queries (e.g., API endpoint).
        """
        raw = self._use_case.execute(snapshot)
        smoothed = self._smoother.update(
            instrument_token=snapshot.instrument_token,
            timeframe=snapshot.timeframe,
            new_primary=raw.primary_regime,
            raw_confidence=raw.confidence,
        )
        return RegimeSnapshot(
            instrument_token=raw.instrument_token,
            timeframe=raw.timeframe,
            primary_regime=smoothed.primary_regime,
            secondary_regime=raw.secondary_regime,
            direction_layer=raw.direction_layer,
            volatility_layer=raw.volatility_layer,
            confidence=smoothed.effective_confidence,
            score=raw.score,
            stability_score=smoothed.stability_score,
            regime_duration_bars=smoothed.duration_bars,
            transition_signal=smoothed.transition_signal,
            explanation=raw.explanation,
            evaluated_at=raw.evaluated_at,
        )

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    async def _on_candle_closed(self, event: CandleClosedEvent) -> None:
        if event.interval != _TARGET_TIMEFRAME:
            return

        key = (event.instrument_token, event.interval)
        feature_snapshot = self._feature_cache.get(key)

        if feature_snapshot is None:
            logger.warning(
                "regime_engine.no_features_cached",
                token=event.instrument_token,
                timeframe=event.interval,
            )
            return

        try:
            result = await self.evaluate(feature_snapshot)
            await self._publish_events(result)
            asyncio.create_task(self._persist(result))
        except Exception:
            logger.exception(
                "regime_engine.evaluation_failed",
                token=event.instrument_token,
                timeframe=event.interval,
            )

    async def _publish_events(self, result: RegimeSnapshot) -> None:
        evaluated_event = MarketRegimeEvaluatedEvent(
            instrument_token=result.instrument_token,
            timeframe=result.timeframe,
            primary_regime=result.primary_regime,
            secondary_regime=result.secondary_regime,
            confidence=result.confidence,
            stability_score=result.stability_score,
            regime_duration_bars=result.regime_duration_bars,
            transition_signal=result.transition_signal,
            direction_layer=result.direction_layer,
            volatility_layer=result.volatility_layer,
            explanation=result.explanation,
        )
        await self._bus.publish(evaluated_event)

        if result.transition_signal:
            # For changed event we need previous regime — read from repository
            prev = await self._repository.get_latest(
                result.instrument_token, result.timeframe
            )
            prev_regime = prev.primary_regime if prev else result.primary_regime

            changed_event = MarketRegimeChangedEvent(
                instrument_token=result.instrument_token,
                timeframe=result.timeframe,
                previous_regime=prev_regime,
                new_regime=result.primary_regime,
                confidence=result.confidence,
                stability_score=result.stability_score,
                regime_duration_bars=result.regime_duration_bars,
            )
            await self._bus.publish(changed_event)

        logger.info(
            "regime_engine.evaluated",
            token=result.instrument_token,
            timeframe=result.timeframe,
            regime=result.primary_regime,
            confidence=result.confidence,
            stability=f"{result.stability_score:.2f}",
            transition=result.transition_signal,
        )

    async def _persist(self, result: RegimeSnapshot) -> None:
        try:
            await self._repository.save(result)
        except Exception:
            logger.exception(
                "regime_engine.persist_failed",
                token=result.instrument_token,
                timeframe=result.timeframe,
            )
