"""Unit tests for SqlAlchemySignalRepository using SQLite in-memory."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.signal import Signal
from core.domain.enums.asset_type import AssetType
from core.domain.enums.market_regime import MarketRegime
from core.domain.enums.signal_state import SignalState
from core.domain.enums.signal_type import SignalType
from core.domain.enums.strategy_type import StrategyType
from core.domain.value_objects.confidence import Confidence
from core.domain.value_objects.score import Score
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.database.repositories.signal_repository import (
    SqlAlchemySignalRepository,
)


def _make_signal() -> Signal:
    return Signal.create(
        symbol=Symbol("NIFTY"),
        signal_type=SignalType.LONG,
        strategy_type=StrategyType.DIRECTIONAL,
        asset_type=AssetType.FNO,
        regime=MarketRegime.TRENDING_BULLISH,
        valid_until=datetime.now(UTC) + timedelta(minutes=30),
    )


class TestSignalRepositorySave:
    async def test_save_and_get_by_id(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemySignalRepository(session_factory)
        signal = _make_signal()
        await repo.save(signal)
        loaded = await repo.get_by_id(signal.signal_id)
        assert loaded is not None
        assert loaded.signal_id == signal.signal_id
        assert loaded.symbol == signal.symbol
        assert loaded.state == SignalState.PENDING

    async def test_get_by_id_missing_returns_none(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemySignalRepository(session_factory)
        result = await repo.get_by_id(uuid.uuid4())
        assert result is None

    async def test_save_updates_existing(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemySignalRepository(session_factory)
        signal = _make_signal()
        await repo.save(signal)
        signal.start_scoring()
        signal.complete_scoring(Score(80), Score(82), Confidence(75), "sha256abc")
        await repo.save(signal)
        loaded = await repo.get_by_id(signal.signal_id)
        assert loaded is not None
        assert loaded.state == SignalState.SCORED
        assert loaded.adjusted_score is not None

    async def test_get_by_state_returns_matching(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemySignalRepository(session_factory)
        s1 = _make_signal()
        s2 = _make_signal()
        s2.start_scoring()
        await repo.save(s1)
        await repo.save(s2)
        pending = await repo.get_by_state(SignalState.PENDING)
        assert len(pending) == 1
        assert pending[0].signal_id == s1.signal_id

    async def test_get_active_excludes_terminal(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemySignalRepository(session_factory)
        active = _make_signal()
        terminal = _make_signal()
        terminal.fail()
        await repo.save(active)
        await repo.save(terminal)
        results = await repo.get_active()
        ids = {r.signal_id for r in results}
        assert active.signal_id in ids
        assert terminal.signal_id not in ids

    async def test_roundtrip_preserves_symbol(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemySignalRepository(session_factory)
        signal = Signal.create(
            symbol=Symbol("BANKNIFTY", "NFO"),
            signal_type=SignalType.SHORT,
            strategy_type=StrategyType.DIRECTIONAL,
            asset_type=AssetType.FNO,
            regime=MarketRegime.TRENDING_BEARISH,
            valid_until=datetime.now(UTC) + timedelta(minutes=15),
        )
        await repo.save(signal)
        loaded = await repo.get_by_id(signal.signal_id)
        assert loaded is not None
        assert loaded.symbol.ticker == "BANKNIFTY"
        assert loaded.symbol.exchange == "NFO"
        assert loaded.signal_type == SignalType.SHORT
