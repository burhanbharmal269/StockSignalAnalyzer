"""OI Analytics configuration — Phase 21.1 Part 19.

All thresholds, intervals, and limits are centralised here.
Nothing is hardcoded in the analytics services.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OIAnalyticsConfig:
    # ── Historical snapshot sampling ──────────────────────────────────────────
    # A snapshot is only persisted if this many seconds have elapsed since the
    # last one for the same symbol.  Matches the default 5-min poll interval.
    snapshot_interval_seconds: int = 300
    snapshot_retention_days: int   = 90

    # ── Regime classification ─────────────────────────────────────────────────
    # Minimum absolute % move required to leave "Neutral"
    regime_price_threshold_pct: float = 0.1   # price axis
    regime_oi_threshold_pct:    float = 0.5   # OI axis (reuses futures_oi_config default)

    # ── OI Quality scoring ────────────────────────────────────────────────────
    # Quote older than this → UNAVAILABLE (0 pts)
    quality_max_age_seconds: int    = 600
    # Fewer rolling-5 observations → quality penalty
    quality_min_observations: int   = 5
    # 12+ rolling-5 observations → Excellent candidate
    quality_excellent_min_obs: int  = 12

    # ── Anomaly detection ─────────────────────────────────────────────────────
    # OI change magnitude > this threshold in a single poll → SPIKE or COLLAPSE
    anomaly_spike_threshold_pct: float  = 20.0
    # Same OI value for this many consecutive polls → FREEZE
    anomaly_freeze_polls: int           = 3
    # Quote older than this → STALE anomaly
    anomaly_stale_threshold_seconds: int = 900

    # ── Market breadth ────────────────────────────────────────────────────────
    breadth_top_movers_count: int = 10

    # ── Failure attribution ───────────────────────────────────────────────────
    failure_min_sample_size: int = 10   # minimum trades before pattern is reported

    # ── Feature evaluation ────────────────────────────────────────────────────
    feature_eval_min_trades: int    = 30
    feature_eval_lookback_days: int = 90

    # ── API / Dashboard limits ────────────────────────────────────────────────
    api_history_max_days: int = 30
    api_symbols_max: int      = 100

    # ── Report scheduling ─────────────────────────────────────────────────────
    daily_report_hour_ist: int  = 16   # 4 PM IST (market close + 30 min buffer)
    weekly_report_weekday: int  = 4    # Friday (0=Monday)
