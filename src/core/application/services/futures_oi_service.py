"""FuturesOIService — Phase 21: Futures Open Interest cache and intelligence.

Maintains an in-memory cache of Futures OI per underlying, populated every
5 minutes by the OptionChainPollerService → OptionChainService.fetch_and_store()
pipeline.  The scanner reads from this cache instead of spot candle OI (which
is always 0 for equity and index spot instruments per Kite API design).

OI change is computed sequentially (current poll minus previous poll), NOT
from oi_day_high/oi_day_low which represent daily extrema only.

All parameters are read from FuturesOIConfig — nothing is hardcoded here.
"""
from __future__ import annotations

import logging
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.infrastructure.config.futures_oi_config import FuturesOIConfig

_log = logging.getLogger(__name__)

# OI direction labels
_INCREASING = "Increasing"
_FALLING    = "Falling"
_FLAT       = "Flat"

# Minimum observations before rolling stats are emitted
_MIN_ROLLING = 3


@dataclass
class FuturesOISnapshot:
    """Live OI state for one underlying's near-month futures contract."""

    underlying: str
    tradingsymbol: str
    instrument_token: int
    expiry: date
    last_price: float
    oi: int
    oi_day_high: int
    oi_day_low: int
    timestamp: datetime

    # Sequential change fields — computed from previous poll, NOT from day extrema
    previous_oi: int | None = None
    previous_timestamp: datetime | None = None
    oi_change: int | None = None
    oi_change_pct: float | None = None
    oi_direction: str | None = None

    # Rolling OI history (maxlen enforced at construction)
    _rolling_5:  deque = field(default_factory=lambda: deque(maxlen=5))
    _rolling_15: deque = field(default_factory=lambda: deque(maxlen=15))
    _rolling_60: deque = field(default_factory=lambda: deque(maxlen=60))

    def rolling_stats(self, window: int) -> dict:
        """Return rolling avg / std / trend for the given window size."""
        buf = {5: self._rolling_5, 15: self._rolling_15, 60: self._rolling_60}.get(window)
        if buf is None or len(buf) < _MIN_ROLLING:
            return {"avg": None, "std": None, "trend": None, "n": len(buf) if buf else 0}
        vals = list(buf)
        avg = statistics.mean(vals)
        std = statistics.stdev(vals) if len(vals) > 1 else 0.0
        trend = "UP" if vals[-1] > vals[0] else ("DOWN" if vals[-1] < vals[0] else "FLAT")
        return {"avg": round(avg, 0), "std": round(std, 0), "trend": trend, "n": len(vals)}


@dataclass
class _Metrics:
    requests: int = 0
    success: int = 0
    failure: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    missing: int = 0
    rolls: int = 0
    latency_sum_ms: float = 0.0
    latency_count: int = 0

    @property
    def avg_latency_ms(self) -> float | None:
        return (
            round(self.latency_sum_ms / self.latency_count, 1)
            if self.latency_count > 0 else None
        )


class FuturesOIService:
    """In-memory Futures OI cache, updated by the OptionChainPollerService cycle.

    Thread safety: single asyncio event loop, no locking needed.
    """

    def __init__(self, config: "FuturesOIConfig | None" = None) -> None:
        from core.infrastructure.config.futures_oi_config import FuturesOIConfig as _Cfg
        self._cfg    = config or _Cfg()
        self._cache: dict[str, FuturesOISnapshot] = {}
        self._metrics = _Metrics()

    # ------------------------------------------------------------------
    # Cache update — called by OptionChainService.fetch_and_store()
    # ------------------------------------------------------------------

    def update(
        self,
        underlying: str,
        tradingsymbol: str,
        instrument_token: int,
        expiry: date,
        last_price: float,
        oi: int,
        oi_day_high: int,
        oi_day_low: int,
        latency_ms: float = 0.0,
    ) -> None:
        """Ingest a fresh futures quote from the option chain poll cycle."""
        self._metrics.requests += 1
        self._metrics.success += 1
        if latency_ms > 0:
            self._metrics.latency_sum_ms += latency_ms
            self._metrics.latency_count  += 1

        now = datetime.now(UTC)
        existing = self._cache.get(underlying)

        # Contract rollover detection — log and clear prior state on expiry change
        if existing and existing.expiry != expiry:
            _log.info(
                "futures_oi.contract_roll underlying=%s %s→%s expiry %s→%s",
                underlying, existing.tradingsymbol, tradingsymbol,
                existing.expiry, expiry,
            )
            self._metrics.rolls += 1
            existing = None  # discard previous-contract state; avoids spurious OI change

        # Preserve rolling buffers across polls for the same contract
        rolling_5  = existing._rolling_5  if existing else deque(maxlen=5)
        rolling_15 = existing._rolling_15 if existing else deque(maxlen=15)
        rolling_60 = existing._rolling_60 if existing else deque(maxlen=60)

        # Sequential OI change — current minus previous poll (NOT oi_day_high/low)
        prev_oi: int | None           = None
        prev_ts: datetime | None      = None
        oi_change: int | None         = None
        oi_change_pct: float | None   = None
        oi_direction: str | None      = None

        if existing is not None and oi is not None:
            prev_oi   = existing.oi
            prev_ts   = existing.timestamp
            oi_change = oi - prev_oi
            if prev_oi > 0:
                oi_change_pct = (oi - prev_oi) / prev_oi * 100.0
                thr = self._cfg.oi_direction_threshold
                if oi_change_pct > thr:
                    oi_direction = _INCREASING
                elif oi_change_pct < -thr:
                    oi_direction = _FALLING
                else:
                    oi_direction = _FLAT

        # Append to rolling buffers (only valid non-zero OI readings)
        if oi and oi > 0:
            rolling_5.append(oi)
            rolling_15.append(oi)
            rolling_60.append(oi)

        snap = FuturesOISnapshot(
            underlying=underlying,
            tradingsymbol=tradingsymbol,
            instrument_token=instrument_token,
            expiry=expiry,
            last_price=last_price,
            oi=oi,
            oi_day_high=oi_day_high,
            oi_day_low=oi_day_low,
            timestamp=now,
            previous_oi=prev_oi,
            previous_timestamp=prev_ts,
            oi_change=oi_change,
            oi_change_pct=oi_change_pct,
            oi_direction=oi_direction,
            _rolling_5=rolling_5,
            _rolling_15=rolling_15,
            _rolling_60=rolling_60,
        )
        self._cache[underlying] = snap

        _log.info(
            "futures_oi.updated underlying=%s tradingsymbol=%s oi=%d "
            "prev_oi=%s change_pct=%s direction=%s",
            underlying, tradingsymbol, oi,
            prev_oi if prev_oi is not None else "N/A",
            f"{oi_change_pct:.2f}%" if oi_change_pct is not None else "N/A",
            oi_direction or "N/A",
        )

    def mark_missing(self, underlying: str, reason: str) -> None:
        """Record that no FUT contract was found for this underlying."""
        self._metrics.missing += 1
        _log.debug("futures_oi.unavailable underlying=%s reason=%s", underlying, reason)

    def mark_failure(self, underlying: str, error: str) -> None:
        """Record a quote fetch failure for this underlying."""
        self._metrics.failure += 1
        _log.warning("futures_oi.failure underlying=%s error=%s", underlying, error)

    # ------------------------------------------------------------------
    # Cache read — called by SignalScannerService per symbol per cycle
    # ------------------------------------------------------------------

    def get_cached(self, underlying: str) -> FuturesOISnapshot | None:
        """Return the latest futures OI snapshot, or None if absent or stale."""
        snap = self._cache.get(underlying)
        if snap is None:
            self._metrics.cache_misses += 1
            return None
        age = (datetime.now(UTC) - snap.timestamp).total_seconds()
        if age > self._cfg.oi_cache_ttl:
            self._metrics.cache_misses += 1
            _log.debug(
                "futures_oi.cache_stale underlying=%s age_secs=%.0f ttl=%d",
                underlying, age, self._cfg.oi_cache_ttl,
            )
            return None
        self._metrics.cache_hits += 1
        return snap

    def has_data(self, underlying: str) -> bool:
        """True if fresh futures OI exists for this underlying."""
        return self.get_cached(underlying) is not None

    # ------------------------------------------------------------------
    # Analytics and observability
    # ------------------------------------------------------------------

    def get_analytics(self) -> dict:
        """Aggregated OI metrics across all cached symbols (for dashboards)."""
        if not self._cache:
            return {
                "symbols_cached": 0,
                "oi_coverage_pct": 0.0,
                "avg_oi": None,
                "avg_oi_change_pct": None,
                "largest_increase_pct": None,
                "largest_decrease_pct": None,
                "avg_intraday_oi_trend": None,
            }

        changes = [
            s.oi_change_pct for s in self._cache.values()
            if s.oi_change_pct is not None
        ]
        avg_oi_raw = (
            statistics.mean([s.oi for s in self._cache.values() if s.oi])
            if self._cache else None
        )
        thr = self._cfg.oi_direction_threshold
        avg_ch = statistics.mean(changes) if changes else 0.0

        return {
            "symbols_cached":       len(self._cache),
            "symbols_with_change":  len(changes),
            "oi_coverage_pct":      round(len(self._cache) / max(len(self._cache), 1) * 100, 1),
            "avg_oi":               round(avg_oi_raw, 0) if avg_oi_raw else None,
            "avg_oi_change_pct":    round(avg_ch, 3) if changes else None,
            "largest_increase_pct": round(max(changes), 3) if changes else None,
            "largest_decrease_pct": round(min(changes), 3) if changes else None,
            "avg_intraday_oi_trend": (
                _INCREASING if avg_ch > thr else (_FALLING if avg_ch < -thr else _FLAT)
            ) if changes else None,
        }

    def get_metrics(self) -> dict:
        """Prometheus-style counters for observability / Grafana."""
        m = self._metrics
        return {
            "futures_oi_requests":     m.requests,
            "futures_oi_success":      m.success,
            "futures_oi_failure":      m.failure,
            "futures_oi_latency_ms":   m.avg_latency_ms,
            "futures_oi_cache_hits":   m.cache_hits,
            "futures_oi_cache_misses": m.cache_misses,
            "futures_oi_missing":      m.missing,
            "futures_oi_rolls":        m.rolls,
        }

    def get_symbol_detail(self, underlying: str) -> dict | None:
        """Full snapshot detail for one symbol (diagnostics / API endpoint)."""
        snap = self._cache.get(underlying)
        if snap is None:
            return None
        now = datetime.now(UTC)
        return {
            "underlying":    snap.underlying,
            "tradingsymbol": snap.tradingsymbol,
            "expiry":        snap.expiry.isoformat(),
            "last_price":    snap.last_price,
            "oi":            snap.oi,
            "oi_day_high":   snap.oi_day_high,
            "oi_day_low":    snap.oi_day_low,
            "previous_oi":   snap.previous_oi,
            "oi_change":     snap.oi_change,
            "oi_change_pct": (
                round(snap.oi_change_pct, 4) if snap.oi_change_pct is not None else None
            ),
            "oi_direction":  snap.oi_direction,
            "timestamp":     snap.timestamp.isoformat(),
            "age_seconds":   round((now - snap.timestamp).total_seconds(), 1),
            "rolling_5":     snap.rolling_stats(5),
            "rolling_15":    snap.rolling_stats(15),
            "rolling_60":    snap.rolling_stats(60),
        }

    def get_all_symbols(self) -> list[dict]:
        """Summary for all cached symbols (for bulk API response)."""
        return [
            {
                "underlying":    s.underlying,
                "tradingsymbol": s.tradingsymbol,
                "expiry":        s.expiry.isoformat(),
                "oi":            s.oi,
                "oi_change_pct": round(s.oi_change_pct, 2) if s.oi_change_pct is not None else None,
                "oi_direction":  s.oi_direction,
                "age_seconds":   round((datetime.now(UTC) - s.timestamp).total_seconds(), 1),
            }
            for s in self._cache.values()
        ]
