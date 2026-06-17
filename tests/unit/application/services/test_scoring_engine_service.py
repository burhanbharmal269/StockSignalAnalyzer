"""Unit tests for ScoringEngineService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.scoring_engine_service import ScoringEngineService
from core.domain.enums.market_regime import MarketRegime
from core.domain.events.signal_events import ScoreCalculated
from core.domain.scoring.score_calculator import ScoreCalculator
from core.domain.value_objects.component_output import ComponentOutput
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.domain.value_objects.score_context import ScoreContext
from core.infrastructure.config.scoring_config import load_scoring_config
from core.infrastructure.config.strategy_config import load_strategy_config

_strategy_cfg = load_strategy_config()
_scoring_cfg = load_scoring_config()


def _make_component(
    name: str,
    max_weight: int,
    direction: str = "LONG",
    score_pct: float = 1.0,
    is_available: bool = True,
) -> MagicMock:
    long_s = float(max_weight) * score_pct if direction != "SHORT" else 0.0
    short_s = float(max_weight) * score_pct if direction == "SHORT" else 0.0
    conviction = score_pct if is_available else 0.0
    output = ComponentOutput(
        component_name=name,
        max_weight=max_weight,
        long_score=long_s if is_available else 0.0,
        short_score=short_s if is_available else 0.0,
        direction=direction if is_available else "NEUTRAL",
        conviction=conviction if is_available else 0.0,
        is_available=is_available,
        data_freshness_seconds=0,
        key_finding=f"{name} finding",
    )
    mock = MagicMock()
    mock.evaluate.return_value = output
    mock.component_name = name
    mock.max_weight = max_weight
    return mock


def _make_service(
    all_direction: str = "LONG",
    event_bus: AsyncMock | None = None,
) -> ScoringEngineService:
    if event_bus is None:
        event_bus = AsyncMock()
    return ScoringEngineService(
        oi_buildup_component=_make_component("OI_BUILDUP", 25, all_direction),
        trend_component=_make_component("TREND", 20, all_direction),
        option_chain_component=_make_component("OPTION_CHAIN", 20, all_direction),
        volume_component=_make_component("VOLUME", 15, all_direction),
        vwap_component=_make_component("VWAP", 10, all_direction),
        sentiment_component=_make_component("SENTIMENT", 5, all_direction),
        iv_analysis_component=_make_component("IV_ANALYSIS", 5, all_direction),
        score_calculator=ScoreCalculator(_strategy_cfg, _scoring_cfg),
        event_bus=event_bus,
    )


def _ctx(regime: MarketRegime = MarketRegime.TRENDING_BULLISH) -> ScoreContext:
    features = FeatureSnapshot(instrument_token=256265, timeframe="15m")
    return ScoreContext(
        instrument_token=256265,
        timeframe="15m",
        regime=regime,
        features=features,
    )


class TestScoringEngineServicePipeline:
    @pytest.mark.asyncio
    async def test_returns_score_result(self) -> None:
        svc = _make_service()
        result = await svc.calculate_score(_ctx())
        assert result is not None
        assert result.direction == "LONG"

    @pytest.mark.asyncio
    async def test_event_published_after_calculation(self) -> None:
        bus = AsyncMock()
        svc = _make_service(event_bus=bus)
        await svc.calculate_score(_ctx())
        bus.publish.assert_called_once()
        event = bus.publish.call_args[0][0]
        assert isinstance(event, ScoreCalculated)

    @pytest.mark.asyncio
    async def test_event_published_for_neutral_direction(self) -> None:
        """ScoreCalculated is always published, even when NEUTRAL."""
        bus = AsyncMock()
        # Make all components tie (equal long and short) → NEUTRAL
        all_neutral = [
            ("OI_BUILDUP", 25), ("TREND", 20), ("OPTION_CHAIN", 20),
            ("VOLUME", 15), ("VWAP", 10), ("SENTIMENT", 5), ("IV_ANALYSIS", 5),
        ]
        components = {}
        for name, w in all_neutral:
            output = ComponentOutput(
                component_name=name, max_weight=w,
                long_score=float(w) / 2, short_score=float(w) / 2,
                direction="NEUTRAL", conviction=0.5,
                is_available=True, data_freshness_seconds=0,
                key_finding=f"{name} neutral",
            )
            m = MagicMock()
            m.evaluate.return_value = output
            m.component_name = name
            m.max_weight = w
            components[name] = m
        svc = ScoringEngineService(
            oi_buildup_component=components["OI_BUILDUP"],
            trend_component=components["TREND"],
            option_chain_component=components["OPTION_CHAIN"],
            volume_component=components["VOLUME"],
            vwap_component=components["VWAP"],
            sentiment_component=components["SENTIMENT"],
            iv_analysis_component=components["IV_ANALYSIS"],
            score_calculator=ScoreCalculator(_strategy_cfg, _scoring_cfg),
            event_bus=bus,
        )
        result = await svc.calculate_score(_ctx())
        bus.publish.assert_called_once()
        assert result.direction == "NEUTRAL"
        assert result.is_eligible is False

    @pytest.mark.asyncio
    async def test_event_fields_match_result(self) -> None:
        bus = AsyncMock()
        svc = _make_service(event_bus=bus)
        result = await svc.calculate_score(_ctx())
        event: ScoreCalculated = bus.publish.call_args[0][0]
        assert event.direction == result.direction
        assert event.adjusted_score == pytest.approx(result.adjusted_score)
        assert event.is_eligible == result.is_eligible
        assert event.weights_sha256 == result.weights_sha256

    @pytest.mark.asyncio
    async def test_event_contains_score_breakdown(self) -> None:
        bus = AsyncMock()
        svc = _make_service(event_bus=bus)
        result = await svc.calculate_score(_ctx())
        event: ScoreCalculated = bus.publish.call_args[0][0]
        bd = result.score_breakdown
        assert event.breakdown_oi_buildup == pytest.approx(bd.oi_buildup)
        assert event.breakdown_trend == pytest.approx(bd.trend)
        assert event.breakdown_option_chain == pytest.approx(bd.option_chain)
        assert event.breakdown_volume == pytest.approx(bd.volume)
        assert event.breakdown_vwap == pytest.approx(bd.vwap)
        assert event.breakdown_sentiment == pytest.approx(bd.sentiment)
        assert event.breakdown_iv_analysis == pytest.approx(bd.iv_analysis)
        assert event.breakdown_regime_alignment == bd.regime_alignment
        assert event.breakdown_regime_mismatch == bd.regime_mismatch
        assert event.breakdown_total == pytest.approx(bd.total_before_penalties)

    @pytest.mark.asyncio
    async def test_event_signal_id_defaults_to_none(self) -> None:
        bus = AsyncMock()
        svc = _make_service(event_bus=bus)
        await svc.calculate_score(_ctx())
        event: ScoreCalculated = bus.publish.call_args[0][0]
        assert event.signal_id is None

    @pytest.mark.asyncio
    async def test_unavailable_component_handled_gracefully(self) -> None:
        bus = AsyncMock()
        svc = ScoringEngineService(
            oi_buildup_component=_make_component("OI_BUILDUP", 25, "LONG", is_available=False),
            trend_component=_make_component("TREND", 20, "LONG"),
            option_chain_component=_make_component("OPTION_CHAIN", 20, "LONG"),
            volume_component=_make_component("VOLUME", 15, "LONG"),
            vwap_component=_make_component("VWAP", 10, "LONG"),
            sentiment_component=_make_component("SENTIMENT", 5, "LONG"),
            iv_analysis_component=_make_component("IV_ANALYSIS", 5, "LONG"),
            score_calculator=ScoreCalculator(_strategy_cfg, _scoring_cfg),
            event_bus=bus,
        )
        result = await svc.calculate_score(_ctx())
        # 6/7 = 85.7% → still eligible
        assert result.data_completeness_pct == pytest.approx(85.71, abs=0.1)
        assert result.is_eligible is True

    @pytest.mark.asyncio
    async def test_insufficient_data_ineligible(self) -> None:
        bus = AsyncMock()
        # 5/7 available = 71.4% < 75%
        svc = ScoringEngineService(
            oi_buildup_component=_make_component("OI_BUILDUP", 25, "LONG", is_available=False),
            trend_component=_make_component("TREND", 20, "LONG", is_available=False),
            option_chain_component=_make_component("OPTION_CHAIN", 20, "LONG"),
            volume_component=_make_component("VOLUME", 15, "LONG"),
            vwap_component=_make_component("VWAP", 10, "LONG"),
            sentiment_component=_make_component("SENTIMENT", 5, "LONG"),
            iv_analysis_component=_make_component("IV_ANALYSIS", 5, "LONG"),
            score_calculator=ScoreCalculator(_strategy_cfg, _scoring_cfg),
            event_bus=bus,
        )
        result = await svc.calculate_score(_ctx())
        assert result.is_eligible is False
        assert result.score_quality == "INSUFFICIENT"

    @pytest.mark.asyncio
    async def test_explanation_attached_to_result(self) -> None:
        svc = _make_service()
        result = await svc.calculate_score(_ctx())
        assert isinstance(result.explanation, list)
        assert len(result.explanation) > 0

    @pytest.mark.asyncio
    async def test_no_signal_labels_in_result(self) -> None:
        svc = _make_service()
        result = await svc.calculate_score(_ctx())
        for word in ("BUY", "SELL", "STRONG_BUY", "STRONG_SELL"):
            assert word not in str(result.direction), f"Signal label '{word}' in direction"
        # score_quality should be quality, not a signal
        assert result.score_quality in ("HIGH", "MEDIUM", "LOW", "INSUFFICIENT")

    @pytest.mark.asyncio
    async def test_weights_sha256_propagated(self) -> None:
        svc = _make_service()
        result = await svc.calculate_score(_ctx())
        assert result.weights_sha256 == _scoring_cfg.sha256
        assert len(result.weights_sha256) == 64  # hex SHA-256

    @pytest.mark.asyncio
    async def test_all_components_evaluated(self) -> None:
        bus = AsyncMock()
        components = {
            name: _make_component(name, w, "LONG")
            for name, w in [
                ("OI_BUILDUP", 25), ("TREND", 20), ("OPTION_CHAIN", 20),
                ("VOLUME", 15), ("VWAP", 10), ("SENTIMENT", 5), ("IV_ANALYSIS", 5),
            ]
        }
        svc = ScoringEngineService(
            oi_buildup_component=components["OI_BUILDUP"],
            trend_component=components["TREND"],
            option_chain_component=components["OPTION_CHAIN"],
            volume_component=components["VOLUME"],
            vwap_component=components["VWAP"],
            sentiment_component=components["SENTIMENT"],
            iv_analysis_component=components["IV_ANALYSIS"],
            score_calculator=ScoreCalculator(_strategy_cfg, _scoring_cfg),
            event_bus=bus,
        )
        await svc.calculate_score(_ctx())
        for comp in components.values():
            comp.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_short_direction_result(self) -> None:
        svc = _make_service(all_direction="SHORT")
        result = await svc.calculate_score(_ctx())
        assert result.direction == "SHORT"

    @pytest.mark.asyncio
    async def test_regime_mismatch_in_event(self) -> None:
        bus = AsyncMock()
        svc = _make_service(event_bus=bus)
        await svc.calculate_score(_ctx(regime=MarketRegime.TRENDING_BEARISH))
        event: ScoreCalculated = bus.publish.call_args[0][0]
        assert event.regime == "TRENDING_BEARISH"
