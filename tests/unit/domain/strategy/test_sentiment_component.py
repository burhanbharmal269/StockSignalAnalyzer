"""Unit tests for SentimentComponent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.domain.strategy.sentiment_component import SentimentComponent
from core.domain.value_objects.sentiment_result import SentimentResult
from core.infrastructure.config.strategy_config import load_strategy_config

from .conftest import _ctx, _features, _sentiment

_cfg = load_strategy_config()


def _comp() -> SentimentComponent:
    return SentimentComponent(_cfg)


class TestSentimentIdentity:
    def test_component_name(self) -> None:
        assert _comp().component_name == "SENTIMENT"

    def test_max_weight(self) -> None:
        assert _comp().max_weight == 5


class TestSentimentNeutralFallback:
    def test_neutral_provider_gives_equal_scores(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            sentiment_result=_sentiment(score=50, is_fallback=True),
        ))
        assert out.is_available
        assert out.long_score == out.short_score
        assert out.direction == "NEUTRAL"

    def test_missing_sentiment_treated_as_neutral(self) -> None:
        out = _comp().evaluate(_ctx(features=_features()))
        assert out.is_available
        assert out.long_score == out.short_score == 2.5

    def test_fallback_flag_in_metadata(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            sentiment_result=_sentiment(is_fallback=True),
        ))
        assert out.metadata["is_fallback"] is True


class TestSentimentBuckets:
    def test_strongly_bullish_maximises_long(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            sentiment_result=_sentiment(score=90, is_fallback=False),
        ))
        assert out.long_score == 5.0
        assert out.short_score == 0.0
        assert out.direction == "LONG"

    def test_bullish_mostly_long(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            sentiment_result=_sentiment(score=70, is_fallback=False),
        ))
        assert out.long_score == 4.0
        assert out.short_score == 1.0

    def test_neutral_splits_evenly(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            sentiment_result=_sentiment(score=50, is_fallback=False),
        ))
        assert out.long_score == 2.5
        assert out.short_score == 2.5

    def test_bearish_mostly_short(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            sentiment_result=_sentiment(score=30, is_fallback=False),
        ))
        assert out.long_score == 1.0
        assert out.short_score == 4.0

    def test_strongly_bearish_maximises_short(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            sentiment_result=_sentiment(score=10, is_fallback=False),
        ))
        assert out.long_score == 0.0
        assert out.short_score == 5.0
        assert out.direction == "SHORT"


class TestSentimentFreshness:
    def test_stale_sentiment_treated_as_neutral(self) -> None:
        stale = SentimentResult(
            score=90,
            provider_name="TestProvider",
            is_fallback=False,
            generated_at=datetime.now(UTC) - timedelta(hours=2),
        )
        out = _comp().evaluate(_ctx(
            features=_features(),
            sentiment_result=stale,
        ))
        # Stale → treated as neutral → equal scores
        assert out.long_score == out.short_score

    def test_fresh_sentiment_used(self) -> None:
        fresh = SentimentResult(
            score=90,
            provider_name="TestProvider",
            is_fallback=False,
            generated_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        out = _comp().evaluate(_ctx(
            features=_features(),
            sentiment_result=fresh,
        ))
        assert out.long_score == 5.0


class TestSentimentScoreBounds:
    def test_scores_capped_at_max_weight(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            sentiment_result=_sentiment(score=100, is_fallback=False),
        ))
        assert out.long_score <= 5.0

    def test_scores_non_negative(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            sentiment_result=_sentiment(score=0, is_fallback=False),
        ))
        assert out.long_score >= 0.0
        assert out.short_score >= 0.0


class TestSentimentResultValidation:
    def test_score_out_of_range_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="0-100"):
            SentimentResult(score=150, provider_name="x", is_fallback=False)

    def test_score_at_boundaries_valid(self) -> None:
        s0 = SentimentResult(score=0, provider_name="x", is_fallback=False)
        s100 = SentimentResult(score=100, provider_name="x", is_fallback=False)
        assert s0.score == 0
        assert s100.score == 100
