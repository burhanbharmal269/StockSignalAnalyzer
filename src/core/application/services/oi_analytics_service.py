"""OI Analytics Service — Phase 21.1.

Orchestrates:
  Part 1  — OI Regime classification (per poll)
  Part 9  — Market Breadth (OI dimension)
  Part 10 — Symbol Health tracking
  Part 11 — OI Quality Score
  Part 12 — Anomaly Detection
  Part 3  — Signal context builder (get_context_for_signal)

Populated by OptionChainService after each FuturesOI update cycle.
All output is read-only intelligence. Zero influence on live trading.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.domain.value_objects.oi_regime import OIQualityTier, OIRegime, classify_oi_regime

if TYPE_CHECKING:
    from core.application.services.futures_oi_service import FuturesOISnapshot
    from core.infrastructure.config.oi_analytics_config import OIAnalyticsConfig
    from core.infrastructure.database.repositories.oi_history_repository import OIHistoryRepository

_log = logging.getLogger(__name__)

# Anomaly type labels (Parts 12)
_ANOMALY_SPIKE    = "SPIKE"
_ANOMALY_COLLAPSE = "COLLAPSE"
_ANOMALY_FREEZE   = "FREEZE"
_ANOMALY_STALE    = "STALE"


class _SymbolState:
    """In-memory per-symbol analytics state — retained across polls."""

    __slots__ = (
        "last_snapshot_at", "last_price", "freeze_count", "last_oi",
        "regime", "quality_tier", "quality_score",
        "is_anomaly", "anomaly_type", "recent_anomalies",
        "poll_count", "poll_success",
    )

    def __init__(self) -> None:
        self.last_snapshot_at: datetime | None = None
        self.last_price: float | None          = None
        self.freeze_count: int                 = 0
        self.last_oi: int | None               = None
        self.regime: OIRegime | None           = None
        self.quality_tier: OIQualityTier | None = None
        self.quality_score: int                = 0
        self.is_anomaly: bool                  = False
        self.anomaly_type: str | None          = None
        self.recent_anomalies: deque           = deque(maxlen=10)
        self.poll_count: int                   = 0
        self.poll_success: int                 = 0


class OIAnalyticsService:
    """Phase 21.1 OI analytics orchestrator.

    Call update_from_snapshot() from OptionChainService after each FuturesOI
    cache update.  All read methods are safe to call from any context.
    """

    def __init__(
        self,
        config: "OIAnalyticsConfig",
        oi_history_repo: "OIHistoryRepository | None" = None,
    ) -> None:
        self._cfg  = config
        self._repo = oi_history_repo
        self._state: dict[str, _SymbolState] = {}
        self._counters = {
            "snapshots_written":    0,
            "regime_updates":       0,
            "quality_updates":      0,
            "anomalies_detected":   0,
        }

    # ── Update path ────────────────────────────────────────────────────────────

    async def update_from_snapshot(
        self,
        snap: "FuturesOISnapshot",
        price_change_pct: float | None = None,
    ) -> None:
        """Ingest a fresh FuturesOI snapshot. Persist history if interval elapsed."""
        sym   = snap.underlying
        state = self._state.setdefault(sym, _SymbolState())
        now   = datetime.now(UTC)

        state.poll_count += 1

        # Compute price change from consecutive futures prices when caller doesn't supply it
        effective_price_chg = price_change_pct
        if effective_price_chg is None and state.last_price and state.last_price > 0:
            effective_price_chg = (snap.last_price - state.last_price) / state.last_price * 100.0

        # OI Quality scoring
        quality_tier, quality_score = self._compute_quality(snap, now)
        state.quality_tier  = quality_tier
        state.quality_score = quality_score
        self._counters["quality_updates"] += 1

        # OI Regime classification
        regime = classify_oi_regime(
            price_change_pct=effective_price_chg,
            oi_change_pct=snap.oi_change_pct,
            price_threshold=self._cfg.regime_price_threshold_pct,
            oi_threshold=self._cfg.regime_oi_threshold_pct,
        )
        state.regime = regime
        self._counters["regime_updates"] += 1

        # Freeze counter
        if state.last_oi is not None and snap.oi == state.last_oi:
            state.freeze_count += 1
        else:
            state.freeze_count = 0
        state.last_oi    = snap.oi
        state.last_price = snap.last_price

        # Anomaly detection
        anomaly = self._detect_anomaly(snap, state, now)
        state.is_anomaly   = anomaly is not None
        state.anomaly_type = anomaly
        if state.is_anomaly:
            self._counters["anomalies_detected"] += 1
            state.recent_anomalies.append({
                "type":          anomaly,
                "at":            now.isoformat(),
                "oi":            snap.oi,
                "oi_change_pct": snap.oi_change_pct,
            })
            _log.warning(
                "oi_analytics.anomaly symbol=%s type=%s oi=%d change_pct=%s",
                sym, anomaly, snap.oi, snap.oi_change_pct,
            )

        # Throttled historical persistence
        elapsed = (
            (now - state.last_snapshot_at).total_seconds()
            if state.last_snapshot_at else float("inf")
        )
        if elapsed >= self._cfg.snapshot_interval_seconds and self._repo is not None:
            row = self._build_history_row(
                snap, regime, quality_tier, quality_score,
                effective_price_chg, anomaly, now,
            )
            await self._repo.add(row)
            state.last_snapshot_at = now
            self._counters["snapshots_written"] += 1
            _log.debug("oi_analytics.snapshot_written symbol=%s regime=%s", sym, regime.value)

        state.poll_success += 1

    # ── Quality scoring (Part 11) ─────────────────────────────────────────────

    def _compute_quality(
        self, snap: "FuturesOISnapshot", now: datetime
    ) -> tuple[OIQualityTier, int]:
        """Return (tier, 0-100 score) based on freshness, observation count, OI validity."""
        # Stale → immediately Unavailable
        age_secs = (now - snap.timestamp).total_seconds()
        if age_secs > self._cfg.quality_max_age_seconds:
            return OIQualityTier.UNAVAILABLE, 0

        score = 100

        # Freshness degradation
        half_ttl      = self._cfg.quality_max_age_seconds * 0.5
        three_qtr_ttl = self._cfg.quality_max_age_seconds * 0.75
        if age_secs > three_qtr_ttl:
            score -= 30
        elif age_secs > half_ttl:
            score -= 15

        # Rolling observation count
        rolling5_n = snap.rolling_stats(5).get("n", 0) or 0
        if rolling5_n < self._cfg.quality_min_observations:
            score -= 25
        elif rolling5_n < self._cfg.quality_excellent_min_obs:
            score -= 8

        # No previous OI means we can't compute sequential change
        if snap.previous_oi is None:
            score -= 10

        # OI of 0 is suspicious (exchange data gap)
        if snap.oi == 0:
            score -= 40

        score = max(0, min(100, score))

        if score >= 85:
            tier = OIQualityTier.EXCELLENT
        elif score >= 65:
            tier = OIQualityTier.GOOD
        elif score >= 40:
            tier = OIQualityTier.FAIR
        else:
            tier = OIQualityTier.POOR

        return tier, score

    # ── Anomaly detection (Part 12) ────────────────────────────────────────────

    def _detect_anomaly(
        self,
        snap: "FuturesOISnapshot",
        state: _SymbolState,
        now: datetime,
    ) -> str | None:
        # Stale quote
        age = (now - snap.timestamp).total_seconds()
        if age > self._cfg.anomaly_stale_threshold_seconds:
            return _ANOMALY_STALE

        # Spike / collapse
        if snap.oi_change_pct is not None:
            thr = self._cfg.anomaly_spike_threshold_pct
            if snap.oi_change_pct > thr:
                return _ANOMALY_SPIKE
            if snap.oi_change_pct < -thr:
                return _ANOMALY_COLLAPSE

        # Frozen OI
        if state.freeze_count >= self._cfg.anomaly_freeze_polls:
            return _ANOMALY_FREEZE

        return None

    # ── History row builder ───────────────────────────────────────────────────

    @staticmethod
    def _build_history_row(
        snap: "FuturesOISnapshot",
        regime: OIRegime,
        quality_tier: OIQualityTier,
        quality_score: int,
        price_change_pct: float | None,
        anomaly_type: str | None,
        now: datetime,
    ) -> dict:
        rs5  = snap.rolling_stats(5)
        rs15 = snap.rolling_stats(15)
        rs60 = snap.rolling_stats(60)
        return {
            "snapshot_at":       now,
            "symbol":            snap.underlying,
            "tradingsymbol":     snap.tradingsymbol,
            "expiry":            snap.expiry,
            "futures_price":     snap.last_price,
            "oi":                snap.oi,
            "previous_oi":       snap.previous_oi,
            "oi_change":         snap.oi_change,
            "oi_change_pct":     round(snap.oi_change_pct, 4) if snap.oi_change_pct is not None else None,
            "oi_direction":      snap.oi_direction,
            "oi_regime":         regime.value,
            "rolling_avg_5":     rs5.get("avg"),
            "rolling_avg_15":    rs15.get("avg"),
            "rolling_avg_60":    rs60.get("avg"),
            "price_change_pct":  round(price_change_pct, 4) if price_change_pct is not None else None,
            "quality_tier":      quality_tier.value,
            "quality_score":     quality_score,
            "cache_age_seconds": int((now - snap.timestamp).total_seconds()),
            "is_anomaly":        anomaly_type is not None,
            "anomaly_type":      anomaly_type,
            "is_contract_roll":  False,
        }

    # ── Read-only public interface ────────────────────────────────────────────

    def get_quality(self, underlying: str) -> dict:
        """Current quality tier + numeric score for one symbol."""
        state = self._state.get(underlying)
        if state is None:
            return {"tier": OIQualityTier.UNAVAILABLE.value, "score": 0}
        return {
            "tier":  (state.quality_tier or OIQualityTier.UNAVAILABLE).value,
            "score": state.quality_score,
        }

    def get_regime(self, underlying: str) -> str | None:
        """Current OI regime label for one symbol, or None."""
        state = self._state.get(underlying)
        return state.regime.value if state and state.regime else None

    def get_symbol_health(self, underlying: str) -> dict | None:
        """Full symbol health report (Part 10)."""
        state = self._state.get(underlying)
        if state is None:
            return None
        return {
            "symbol":             underlying,
            "poll_count":         state.poll_count,
            "poll_success":       state.poll_success,
            "poll_success_pct":   round(state.poll_success / max(state.poll_count, 1) * 100, 1),
            "quality_tier":       (state.quality_tier or OIQualityTier.UNAVAILABLE).value,
            "quality_score":      state.quality_score,
            "regime":             state.regime.value if state.regime else None,
            "is_anomaly":         state.is_anomaly,
            "anomaly_type":       state.anomaly_type,
            "recent_anomalies":   list(state.recent_anomalies),
            "last_snapshot_at":   state.last_snapshot_at.isoformat() if state.last_snapshot_at else None,
        }

    def get_all_health(self) -> list[dict]:
        """Health report for all tracked symbols."""
        return [h for sym in self._state if (h := self.get_symbol_health(sym)) is not None]

    def get_coverage_summary(self) -> dict:
        """OI coverage and quality distribution across all tracked symbols."""
        states = list(self._state.values())
        if not states:
            return {"symbols_tracked": 0}
        tiers: dict[str, int] = defaultdict(int)
        for s in states:
            tiers[(s.quality_tier or OIQualityTier.UNAVAILABLE).value] += 1
        n = len(states)
        available = n - tiers.get(OIQualityTier.UNAVAILABLE.value, 0)
        return {
            "symbols_tracked":       n,
            "symbols_available":     available,
            "coverage_pct":          round(available / n * 100, 1) if n else 0.0,
            "quality_distribution":  dict(tiers),
        }

    def get_market_breadth_oi(self) -> dict:
        """Live OI-based market breadth from in-memory state (Part 9)."""
        states = [
            s for s in self._state.values()
            if s.quality_tier not in (OIQualityTier.UNAVAILABLE, None)
        ]
        n = len(states)
        if not n:
            return {"symbols_tracked": 0}

        regimes = [s.regime for s in states if s.regime not in (OIRegime.UNKNOWN, None)]
        regime_counts: dict[str, int] = defaultdict(int)
        for r in regimes:
            regime_counts[r.value] += 1

        return {
            "symbols_tracked":    n,
            "regime_distribution": dict(regime_counts),
            "long_buildup_pct":   round(regime_counts.get(OIRegime.LONG_BUILDUP.value,   0) / n * 100, 1),
            "short_buildup_pct":  round(regime_counts.get(OIRegime.SHORT_BUILDUP.value,  0) / n * 100, 1),
            "long_unwind_pct":    round(regime_counts.get(OIRegime.LONG_UNWINDING.value, 0) / n * 100, 1),
            "short_cover_pct":    round(regime_counts.get(OIRegime.SHORT_COVERING.value, 0) / n * 100, 1),
            "neutral_pct":        round(regime_counts.get(OIRegime.NEUTRAL.value,        0) / n * 100, 1),
            "anomalies_active":   sum(1 for s in states if s.is_anomaly),
        }

    def get_anomalies(self) -> list[dict]:
        """All symbols currently in an anomalous OI state."""
        return [
            {
                "symbol":           sym,
                "anomaly_type":     state.anomaly_type,
                "recent_anomalies": list(state.recent_anomalies),
            }
            for sym, state in self._state.items()
            if state.is_anomaly
        ]

    def get_context_for_signal(
        self,
        underlying: str,
        snap: "FuturesOISnapshot | None",
    ) -> dict:
        """Build OI context dict for inclusion in signal_analytics.record() (Part 3)."""
        state = self._state.get(underlying)
        if snap is None:
            return {}
        now = datetime.now(UTC)
        return {
            "futures_oi":              snap.oi,
            "oi_change":               snap.oi_change,
            "oi_change_pct":           round(snap.oi_change_pct, 4) if snap.oi_change_pct is not None else None,
            "oi_direction":            snap.oi_direction,
            "oi_regime":               state.regime.value if state and state.regime else None,
            "futures_contract":        snap.tradingsymbol,
            "oi_quality_score":        (state.quality_tier or OIQualityTier.UNAVAILABLE).value if state else None,
            "quote_freshness_seconds": int((now - snap.timestamp).total_seconds()),
        }

    def get_metrics(self) -> dict:
        """Prometheus-style counters for Grafana integration (Part 18)."""
        return {
            **self._counters,
            "symbols_tracked": len(self._state),
        }
