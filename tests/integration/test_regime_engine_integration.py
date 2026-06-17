"""Integration tests for the Market Regime Engine end-to-end pipeline.

Tests the full pipeline: FeatureSnapshot → RegimeEvaluationUseCase →
RegimeSmoother → RegimeSnapshot, plus event publishing and persistence.
Uses InMemoryEventBus to avoid Redis dependency.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from core.application.services.regime_engine_service import MarketRegimeService
from core.application.use_cases.regime_evaluation_use_case import RegimeEvaluationUseCase
from core.domain.enums.market_regime import MarketRegime
from core.domain.events.market_events import CandleClosedEvent
from core.domain.events.regime_events import (
    MarketRegimeChangedEvent,
    MarketRegimeEvaluatedEvent,
)
from core.domain.regime.confidence_calculator import ConfidenceCalculator
from core.domain.regime.regime_resolver import RegimeResolver
from core.domain.regime.regime_smoother import RegimeSmoother
from core.domain.regime.trend_layer import TrendLayer
from core.domain.regime.volatility_layer import VolatilityLayer
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.infrastructure.config.regime_config import load_regime_config
from core.infrastructure.events.in_memory_event_bus import InMemoryEventBus


@pytest.fixture
def cfg():
    return load_regime_config()


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


@pytest.fixture
def use_case(cfg):
    return RegimeEvaluationUseCase(
        trend_layer=TrendLayer(cfg),
        volatility_layer=VolatilityLayer(cfg),
        resolver=RegimeResolver(cfg),
        confidence_calculator=ConfidenceCalculator(cfg),
    )


@pytest.fixture
def smoother(cfg):
    return RegimeSmoother(cfg)


class _InMemoryRegimeRepository:
    def __init__(self):
        self._store: list = []

    async def save(self, snapshot) -> None:
        self._store.append(snapshot)

    async def get_latest(self, instrument_token, timeframe):
        matches = [
            s for s in self._store
            if s.instrument_token == instrument_token and s.timeframe == timeframe
        ]
        return matches[-1] if matches else None

    async def get_history(self, instrument_token, timeframe, since):
        return [
            s for s in self._store
            if s.instrument_token == instrument_token
            and s.timeframe == timeframe
            and s.evaluated_at >= since
        ]


@pytest.fixture
def repo():
    return _InMemoryRegimeRepository()


@pytest.fixture
def service(use_case, smoother, repo, event_bus):
    return MarketRegimeService(
        evaluation_use_case=use_case,
        smoother=smoother,
        regime_repository=repo,
        event_bus=event_bus,
    )


def _feature_snap(token: int = 256265, **kwargs) -> FeatureSnapshot:
    return FeatureSnapshot(**{"instrument_token": token, "timeframe": "15m", **kwargs})


def _candle_event(token: int = 256265, interval: str = "15m") -> CandleClosedEvent:
    from decimal import Decimal

    return CandleClosedEvent(
        instrument_token=token,
        tradingsymbol="NIFTY",
        exchange="NSE",
        interval=interval,
        open=Decimal("22000"),
        high=Decimal("22100"),
        low=Decimal("21900"),
        close=Decimal("22050"),
        volume=100000,
        opened_at=datetime.now(UTC),
        closed_at=datetime.now(UTC),
    )


class TestRegimeEngineIntegration:
    @pytest.mark.asyncio
    async def test_evaluate_returns_regime_snapshot(self, service) -> None:
        snap = _feature_snap(india_vix=18.0, adx=30.0, di_plus=35.0, di_minus=15.0)
        result = await service.evaluate(snap)
        assert result.primary_regime == MarketRegime.TRENDING_BULLISH
        assert 0 <= result.confidence <= 100

    @pytest.mark.asyncio
    async def test_panic_vix_gives_high_volatility(self, service) -> None:
        snap = _feature_snap(india_vix=31.0)
        result = await service.evaluate(snap)
        assert result.primary_regime == MarketRegime.HIGH_VOLATILITY

    @pytest.mark.asyncio
    async def test_smoothing_increases_stability(self, service) -> None:
        snap = _feature_snap(india_vix=18.0)
        s1 = await service.evaluate(snap)
        s2 = await service.evaluate(snap)
        s3 = await service.evaluate(snap)
        assert s3.stability_score >= s2.stability_score >= s1.stability_score

    @pytest.mark.asyncio
    async def test_candle_close_publishes_evaluated_event(
        self, service, event_bus
    ) -> None:
        await service.start()
        snap = _feature_snap(india_vix=18.0)
        await service.update_features(snap)
        await service._on_candle_closed(_candle_event())
        await asyncio.sleep(0.05)

        evaluated = event_bus.published_events(MarketRegimeEvaluatedEvent)
        assert len(evaluated) >= 1
        assert evaluated[0].instrument_token == 256265

    @pytest.mark.asyncio
    async def test_non_15m_candle_ignored(self, service, event_bus) -> None:
        await service.start()
        snap = _feature_snap(india_vix=18.0)
        await service.update_features(snap)
        await service._on_candle_closed(_candle_event(interval="5m"))
        await asyncio.sleep(0.05)

        evaluated = event_bus.published_events(MarketRegimeEvaluatedEvent)
        assert len(evaluated) == 0

    @pytest.mark.asyncio
    async def test_no_features_cached_does_not_crash(self, service) -> None:
        await service.start()
        await service._on_candle_closed(_candle_event())
        # No exception raised

    @pytest.mark.asyncio
    async def test_transition_publishes_changed_event(
        self, service, event_bus, repo
    ) -> None:
        await service.start()

        # First: SIDEWAYS (no indicators)
        sideways_snap = _feature_snap(token=1)
        await service.update_features(sideways_snap)
        await service._on_candle_closed(_candle_event(token=1))
        await asyncio.sleep(0.05)

        # Second: HIGH_VOLATILITY (panic VIX)
        panic_snap = _feature_snap(token=1, india_vix=31.0)
        await service.update_features(panic_snap)
        await service._on_candle_closed(_candle_event(token=1))
        await asyncio.sleep(0.05)

        changed = event_bus.published_events(MarketRegimeChangedEvent)
        assert len(changed) >= 1

    @pytest.mark.asyncio
    async def test_update_features_caches_snapshot(self, service) -> None:
        snap = _feature_snap(india_vix=18.0)
        await service.update_features(snap)
        key = (snap.instrument_token, snap.timeframe)
        assert key in service._feature_cache
        assert service._feature_cache[key].india_vix == 18.0
