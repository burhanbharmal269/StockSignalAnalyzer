"""Feature Registry — Phase 21.1 Part 22.

Generic registry for all market features used by the platform.
Pre-registers the known feature set at startup.  Analytics modules
(Component Attribution, Failure Attribution, Walk-Forward, Deployment
Readiness, TMI, AI research) query this registry instead of hardcoding
feature lists.

Adding a new feature requires only one registration call — no changes
to any analytics consumer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

_log = logging.getLogger(__name__)


@dataclass
class FeatureMetadata:
    name: str
    category: str                        # technical | options | market_structure | sentiment | oi
    source: str                          # kite | nse | computed | internal
    version: str                         = "1.0"
    refresh_frequency_seconds: int       = 300
    dependencies: list[str]              = field(default_factory=list)
    quality_score: float | None          = None   # 0-100
    availability_pct: float | None       = None   # 0-100
    predictive_power: float | None       = None   # 0-1 (higher = more predictive)
    current_status: str                  = "ACTIVE"  # ACTIVE | DEGRADED | UNAVAILABLE
    registered_at: datetime              = field(default_factory=lambda: datetime.now(UTC))
    last_updated_at: datetime | None     = None


class FeatureRegistry:
    """Singleton-style in-memory registry of all feature metadata.

    Thread-safe for reads; writes are infrequent (startup + periodic analytics
    updates run inside the asyncio event loop).
    """

    def __init__(self) -> None:
        self._features: dict[str, FeatureMetadata] = {}
        self._register_platform_defaults()

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    def _register_platform_defaults(self) -> None:
        """Pre-register every known platform feature at startup."""
        defaults = [
            # Technical
            FeatureMetadata("trend",          "technical",        "computed",  refresh_frequency_seconds=60),
            FeatureMetadata("volume",          "technical",        "kite",      refresh_frequency_seconds=60),
            FeatureMetadata("vwap",            "technical",        "computed",  refresh_frequency_seconds=60),
            FeatureMetadata("rsi",             "technical",        "computed",  refresh_frequency_seconds=60),
            FeatureMetadata("adx",             "technical",        "computed",  refresh_frequency_seconds=60),
            FeatureMetadata("mtf",             "technical",        "computed",  refresh_frequency_seconds=60,
                            dependencies=["trend"]),
            # Options
            FeatureMetadata("option_chain",    "options",          "kite",      refresh_frequency_seconds=300),
            FeatureMetadata("oi_buildup",      "options",          "computed",  refresh_frequency_seconds=300,
                            dependencies=["option_chain"]),
            FeatureMetadata("iv",              "options",          "kite",      refresh_frequency_seconds=300,
                            dependencies=["option_chain"]),
            # Market structure
            FeatureMetadata("pcr",             "market_structure", "computed",  refresh_frequency_seconds=300,
                            dependencies=["option_chain"]),
            FeatureMetadata("gex",             "market_structure", "computed",  refresh_frequency_seconds=300,
                            dependencies=["option_chain"]),
            FeatureMetadata("futures_oi",      "market_structure", "kite",      refresh_frequency_seconds=300),
            FeatureMetadata("market_context",  "market_structure", "computed",  refresh_frequency_seconds=300,
                            dependencies=["regime", "vix", "breadth"]),
            FeatureMetadata("regime",          "market_structure", "computed",  refresh_frequency_seconds=300),
            FeatureMetadata("vix",             "market_structure", "kite",      refresh_frequency_seconds=300),
            FeatureMetadata("breadth",         "market_structure", "computed",  refresh_frequency_seconds=300),
            # Sentiment
            FeatureMetadata("sentiment",       "sentiment",        "internal",  refresh_frequency_seconds=3600),
        ]
        for f in defaults:
            self._features[f.name] = f
        _log.debug("feature_registry.bootstrapped count=%d", len(self._features))

    # ── Mutation ──────────────────────────────────────────────────────────────

    def register(self, name: str, metadata: FeatureMetadata) -> None:
        """Register or replace a feature."""
        self._features[name] = metadata
        _log.debug("feature_registry.registered name=%s category=%s", name, metadata.category)

    def update_quality(
        self,
        name: str,
        quality_score: float,
        availability_pct: float,
        status: str = "ACTIVE",
    ) -> None:
        """Update quality metrics for an existing feature."""
        f = self._features.get(name)
        if f is None:
            _log.warning("feature_registry.unknown_feature name=%s — skipping update", name)
            return
        f.quality_score     = quality_score
        f.availability_pct  = availability_pct
        f.current_status    = status
        f.last_updated_at   = datetime.now(UTC)

    def update_predictive_power(self, name: str, power: float) -> None:
        """Set or update the measured predictive power (0-1) for a feature."""
        f = self._features.get(name)
        if f:
            f.predictive_power  = power
            f.last_updated_at   = datetime.now(UTC)

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get(self, name: str) -> FeatureMetadata | None:
        return self._features.get(name)

    def get_all(self) -> list[dict]:
        """All features in registration order."""
        return [self._to_dict(f) for f in self._features.values()]

    def get_ranked(self) -> list[dict]:
        """Features sorted by predictive_power descending (unranked last)."""
        items = sorted(
            self._features.values(),
            key=lambda f: f.predictive_power if f.predictive_power is not None else -1.0,
            reverse=True,
        )
        return [self._to_dict(f) for f in items]

    def get_by_category(self, category: str) -> list[dict]:
        return [
            self._to_dict(f) for f in self._features.values()
            if f.category == category
        ]

    def get_degraded(self) -> list[dict]:
        return [
            self._to_dict(f) for f in self._features.values()
            if f.current_status in ("DEGRADED", "UNAVAILABLE")
        ]

    # ── Serialisation ─────────────────────────────────────────────────────────

    @staticmethod
    def _to_dict(f: FeatureMetadata) -> dict:
        return {
            "name":                      f.name,
            "category":                  f.category,
            "source":                    f.source,
            "version":                   f.version,
            "refresh_frequency_seconds": f.refresh_frequency_seconds,
            "dependencies":              f.dependencies,
            "quality_score":             f.quality_score,
            "availability_pct":          f.availability_pct,
            "predictive_power":          f.predictive_power,
            "current_status":            f.current_status,
            "registered_at":             f.registered_at.isoformat(),
            "last_updated_at":           f.last_updated_at.isoformat() if f.last_updated_at else None,
        }
