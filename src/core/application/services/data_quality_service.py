"""DataQualityService — pure computation of feed freshness at signal time.

Monitoring-only. Never called from the scoring or confidence pipeline.
Called once per symbol after all data sources have been queried, so the
scanner can record a quality score alongside each signal analytics row.

Inputs (all keyword-only to force explicit use):
  option_chain_age_minutes  — minutes since oc_snap.snapshot_timestamp (None = no chain)
  has_oi                    — oi_change_pct is not None
  has_5m_candles            — mtf_5m is not None
  has_vix                   — india_vix is not None
  has_gex                   — oc_snap.gex_positive is not None
  underlying_candle_age_min — minutes since most recent 15m candle close (None = unknown)
"""

from __future__ import annotations

import logging

from core.domain.value_objects.data_quality_report import DataQualityReport

_log = logging.getLogger(__name__)

_CHAIN_STALE_MINUTES     = 5.0
_CANDLE_STALE_MINUTES    = 20.0   # 15m candle + 5m grace

_PENALTY_STALE_CHAIN     = 20
_PENALTY_MISSING_OI      = 20
_PENALTY_NO_5M_CANDLES   = 20
_PENALTY_NO_VIX          = 20
_PENALTY_NO_GEX          = 10
_PENALTY_STALE_CANDLES   = 20


class DataQualityService:
    """Stateless: one instance per process, called per symbol per cycle."""

    def compute(
        self,
        *,
        option_chain_age_minutes: float | None,
        has_oi: bool,
        has_5m_candles: bool,
        has_vix: bool,
        has_gex: bool,
        underlying_candle_age_minutes: float | None,
    ) -> DataQualityReport:
        score = 100
        missing: list[str] = []
        stale: list[str]   = []

        # Option chain staleness
        if option_chain_age_minutes is None:
            score -= _PENALTY_STALE_CHAIN
            missing.append("option_chain")
        elif option_chain_age_minutes > _CHAIN_STALE_MINUTES:
            score -= _PENALTY_STALE_CHAIN
            stale.append("option_chain")

        # OI data
        if not has_oi:
            score -= _PENALTY_MISSING_OI
            missing.append("oi_data")

        # 5-minute candles (MTF)
        if not has_5m_candles:
            score -= _PENALTY_NO_5M_CANDLES
            missing.append("5m_candles")

        # India VIX
        if not has_vix:
            score -= _PENALTY_NO_VIX
            missing.append("india_vix")

        # GEX
        if not has_gex:
            score -= _PENALTY_NO_GEX
            missing.append("gex")

        # Underlying candle freshness
        if underlying_candle_age_minutes is None:
            score -= _PENALTY_STALE_CANDLES
            stale.append("underlying_candles")
        elif underlying_candle_age_minutes > _CANDLE_STALE_MINUTES:
            score -= _PENALTY_STALE_CANDLES
            stale.append("underlying_candles")

        score = max(0, score)
        report = DataQualityReport(score=score, missing_sources=missing, stale_feeds=stale)

        if report.is_critical:
            _log.warning(
                "data_quality.CRITICAL score=%d missing=%s stale=%s",
                score, missing, stale,
            )
        elif not report.is_acceptable:
            _log.warning(
                "data_quality.DEGRADED score=%d missing=%s stale=%s",
                score, missing, stale,
            )

        return report
