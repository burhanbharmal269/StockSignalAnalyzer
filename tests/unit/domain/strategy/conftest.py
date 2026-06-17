"""Shared fixtures for strategy component unit tests."""

from __future__ import annotations

import pytest

from core.domain.enums.market_regime import MarketRegime
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.domain.value_objects.option_chain_snapshot import OptionChainSnapshot
from core.domain.value_objects.score_context import ScoreContext
from core.domain.value_objects.sentiment_result import SentimentResult
from core.infrastructure.config.strategy_config import load_strategy_config


@pytest.fixture(scope="session")
def cfg():
    return load_strategy_config()


def _features(**kwargs) -> FeatureSnapshot:
    return FeatureSnapshot(**{"instrument_token": 256265, "timeframe": "15m", **kwargs})


def _ctx(
    regime: MarketRegime = MarketRegime.TRENDING_BULLISH,
    features: FeatureSnapshot | None = None,
    **kwargs,
) -> ScoreContext:
    return ScoreContext(
        instrument_token=256265,
        timeframe="15m",
        regime=regime,
        features=features or _features(),
        **kwargs,
    )


def _oc(**kwargs) -> OptionChainSnapshot:
    return OptionChainSnapshot(**kwargs)


def _sentiment(score: int = 50, is_fallback: bool = True) -> SentimentResult:
    return SentimentResult(
        score=score,
        provider_name="NeutralSentimentProvider" if is_fallback else "TestProvider",
        is_fallback=is_fallback,
    )
