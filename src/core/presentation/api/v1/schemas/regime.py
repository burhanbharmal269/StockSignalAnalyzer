"""Pydantic response schemas for the Market Regime Engine API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from core.domain.enums.market_regime import MarketRegime


class RegimeSnapshotResponse(BaseModel):
    """API response for a single regime snapshot."""

    instrument_token: int
    timeframe: str
    primary_regime: MarketRegime
    secondary_regime: MarketRegime | None
    direction_layer: str
    volatility_layer: str
    confidence: int
    score: float
    stability_score: float
    regime_duration_bars: int
    transition_signal: bool
    explanation: list[str]
    evaluated_at: datetime

    model_config = {"from_attributes": True}


class RegimeHistoryResponse(BaseModel):
    """API response for regime history list."""

    instrument_token: int
    timeframe: str
    snapshots: list[RegimeSnapshotResponse]
