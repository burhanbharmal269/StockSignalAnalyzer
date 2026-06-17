"""Unit tests for NeutralSentimentProvider."""

from __future__ import annotations

import pytest

from core.infrastructure.providers.neutral_sentiment_provider import NeutralSentimentProvider


@pytest.fixture
def provider() -> NeutralSentimentProvider:
    return NeutralSentimentProvider()


class TestNeutralSentimentProviderIdentity:
    def test_provider_name(self, provider: NeutralSentimentProvider) -> None:
        assert provider.provider_name == "NeutralSentimentProvider"

    def test_is_fallback_true(self, provider: NeutralSentimentProvider) -> None:
        assert provider.is_fallback is True


class TestNeutralSentimentProviderOutput:
    @pytest.mark.asyncio
    async def test_returns_score_50(self, provider: NeutralSentimentProvider) -> None:
        result = await provider.get_sentiment("NIFTY")
        assert result.score == 50

    @pytest.mark.asyncio
    async def test_result_is_fallback(self, provider: NeutralSentimentProvider) -> None:
        result = await provider.get_sentiment("BANKNIFTY")
        assert result.is_fallback is True

    @pytest.mark.asyncio
    async def test_provider_name_in_result(self, provider: NeutralSentimentProvider) -> None:
        result = await provider.get_sentiment("NIFTY")
        assert result.provider_name == "NeutralSentimentProvider"

    @pytest.mark.asyncio
    async def test_ignores_symbol_parameter(self, provider: NeutralSentimentProvider) -> None:
        r1 = await provider.get_sentiment("NIFTY")
        r2 = await provider.get_sentiment("BANKNIFTY")
        assert r1.score == r2.score

    @pytest.mark.asyncio
    async def test_result_score_in_valid_range(
        self, provider: NeutralSentimentProvider
    ) -> None:
        result = await provider.get_sentiment("FINNIFTY")
        assert 0 <= result.score <= 100
