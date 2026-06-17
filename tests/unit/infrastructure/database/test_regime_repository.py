"""Unit tests for SqlAlchemyRegimeRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.domain.enums.market_regime import MarketRegime
from core.domain.value_objects.regime_snapshot import RegimeSnapshot
from core.infrastructure.database.repositories.regime_repository import (
    SqlAlchemyRegimeRepository,
)


def _snapshot(
    token: int = 256265,
    timeframe: str = "15m",
    regime: MarketRegime = MarketRegime.SIDEWAYS,
    confidence: int = 65,
    evaluated_at: datetime | None = None,
    transition: bool = False,
) -> RegimeSnapshot:
    return RegimeSnapshot(
        instrument_token=token,
        timeframe=timeframe,
        primary_regime=regime,
        secondary_regime=None,
        direction_layer="NEUTRAL",
        volatility_layer="NORMAL",
        confidence=confidence,
        score=float(confidence),
        stability_score=0.8,
        regime_duration_bars=5,
        transition_signal=transition,
        explanation=("ADX weak",),
        evaluated_at=evaluated_at or datetime.now(UTC),
    )


class TestRegimeRepositorySave:
    @pytest.mark.asyncio
    async def test_save_and_get_latest(self, session_factory) -> None:
        repo = SqlAlchemyRegimeRepository(session_factory)
        snap = _snapshot()
        await repo.save(snap)
        result = await repo.get_latest(snap.instrument_token, snap.timeframe)
        assert result is not None
        assert result.primary_regime == MarketRegime.SIDEWAYS
        assert result.instrument_token == snap.instrument_token

    @pytest.mark.asyncio
    async def test_get_latest_returns_none_when_empty(self, session_factory) -> None:
        repo = SqlAlchemyRegimeRepository(session_factory)
        result = await repo.get_latest(99999, "15m")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_returns_most_recent(self, session_factory) -> None:
        repo = SqlAlchemyRegimeRepository(session_factory)
        now = datetime.now(UTC)
        snap1 = _snapshot(regime=MarketRegime.SIDEWAYS, evaluated_at=now - timedelta(minutes=15))
        snap2 = _snapshot(regime=MarketRegime.TRENDING_BULLISH, evaluated_at=now)
        await repo.save(snap1)
        await repo.save(snap2)
        result = await repo.get_latest(snap1.instrument_token, snap1.timeframe)
        assert result is not None
        assert result.primary_regime == MarketRegime.TRENDING_BULLISH

    @pytest.mark.asyncio
    async def test_save_with_secondary_regime(self, session_factory) -> None:
        repo = SqlAlchemyRegimeRepository(session_factory)
        snap = RegimeSnapshot(
            instrument_token=1,
            timeframe="15m",
            primary_regime=MarketRegime.TRENDING_BULLISH,
            secondary_regime=MarketRegime.HIGH_VOLATILITY,
            direction_layer="BULLISH",
            volatility_layer="HIGH",
            confidence=70,
            score=70.0,
            stability_score=0.5,
            regime_duration_bars=2,
            transition_signal=True,
            explanation=("test",),
            evaluated_at=datetime.now(UTC),
        )
        await repo.save(snap)
        result = await repo.get_latest(1, "15m")
        assert result is not None
        assert result.secondary_regime == MarketRegime.HIGH_VOLATILITY
        assert result.transition_signal is True


class TestRegimeRepositoryHistory:
    @pytest.mark.asyncio
    async def test_get_history_returns_ordered_list(self, session_factory) -> None:
        repo = SqlAlchemyRegimeRepository(session_factory)
        now = datetime.now(UTC)
        snaps = [
            _snapshot(evaluated_at=now - timedelta(hours=i), regime=MarketRegime.SIDEWAYS)
            for i in range(3)
        ]
        for s in snaps:
            await repo.save(s)
        since = now - timedelta(hours=5)
        result = await repo.get_history(256265, "15m", since)
        assert len(result) == 3
        for i in range(len(result) - 1):
            assert result[i].evaluated_at <= result[i + 1].evaluated_at

    @pytest.mark.asyncio
    async def test_get_history_filters_by_since(self, session_factory) -> None:
        repo = SqlAlchemyRegimeRepository(session_factory)
        now = datetime.now(UTC)
        old = _snapshot(evaluated_at=now - timedelta(hours=10))
        recent = _snapshot(evaluated_at=now - timedelta(hours=1))
        await repo.save(old)
        await repo.save(recent)
        since = now - timedelta(hours=5)
        result = await repo.get_history(256265, "15m", since)
        assert len(result) == 1
        assert result[0].evaluated_at >= since

    @pytest.mark.asyncio
    async def test_explanation_roundtrip(self, session_factory) -> None:
        repo = SqlAlchemyRegimeRepository(session_factory)
        snap = _snapshot()
        await repo.save(snap)
        result = await repo.get_latest(snap.instrument_token, snap.timeframe)
        assert result is not None
        assert result.explanation == snap.explanation
