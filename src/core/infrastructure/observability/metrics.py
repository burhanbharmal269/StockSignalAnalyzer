"""Prometheus metrics registry and factory helpers.

Pre-built application-level metrics live here as module-level singletons so
they are registered exactly once per process. Custom metrics for individual
subsystems should be created with the factory functions, passing an explicit
registry in tests to avoid polluting the global REGISTRY.

Reference: docs/09_CLAUDE_EXECUTION_RULES.md (Observability Rules)
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# ---------------------------------------------------------------------------
# Pre-built HTTP metrics (registered in the global REGISTRY at import time)
# ---------------------------------------------------------------------------

HTTP_REQUESTS_TOTAL: Counter = Counter(
    "http_requests_total",
    "Total HTTP requests processed, partitioned by method, path, and status code.",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION_SECONDS: Histogram = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds, partitioned by method and path.",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ---------------------------------------------------------------------------
# Factory functions for subsystem-specific metrics
# ---------------------------------------------------------------------------


def make_counter(
    name: str,
    description: str,
    labels: list[str] | None = None,
    registry: CollectorRegistry | None = None,
) -> Counter:
    """Create and register a Counter metric.

    Args:
        name: Prometheus metric name (snake_case, e.g. ``orders_total``).
        description: Human-readable help string shown in /metrics output.
        labels: Optional label names for partitioning (e.g. ``["status"]``).
        registry: Pass a fresh CollectorRegistry() in tests to avoid global
                  pollution. Defaults to the global REGISTRY.
    """
    kwargs: dict[str, CollectorRegistry] = {}
    if registry is not None:
        kwargs["registry"] = registry
    return Counter(name, description, labels or [], **kwargs)


def make_histogram(
    name: str,
    description: str,
    labels: list[str] | None = None,
    buckets: tuple[float, ...] = Histogram.DEFAULT_BUCKETS,  # type: ignore[assignment]
    registry: CollectorRegistry | None = None,
) -> Histogram:
    """Create and register a Histogram metric."""
    kwargs: dict[str, CollectorRegistry] = {}
    if registry is not None:
        kwargs["registry"] = registry
    return Histogram(name, description, labels or [], buckets=buckets, **kwargs)


def make_gauge(
    name: str,
    description: str,
    labels: list[str] | None = None,
    registry: CollectorRegistry | None = None,
) -> Gauge:
    """Create and register a Gauge metric."""
    kwargs: dict[str, CollectorRegistry] = {}
    if registry is not None:
        kwargs["registry"] = registry
    return Gauge(name, description, labels or [], **kwargs)


def get_metrics_output() -> tuple[bytes, str]:
    """Return (content, content_type) ready for the /metrics endpoint response."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
