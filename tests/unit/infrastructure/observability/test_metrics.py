"""Unit tests for Prometheus metrics factory and helpers."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from core.infrastructure.observability.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    get_metrics_output,
    make_counter,
    make_gauge,
    make_histogram,
)


class TestPrebuiltMetrics:
    def test_http_requests_total_is_counter(self) -> None:
        assert isinstance(HTTP_REQUESTS_TOTAL, Counter)

    def test_http_request_duration_seconds_is_histogram(self) -> None:
        assert isinstance(HTTP_REQUEST_DURATION_SECONDS, Histogram)

    def test_http_requests_total_has_expected_labels(self) -> None:
        # Accessing _labelnames is the standard way to inspect in prometheus_client
        assert set(HTTP_REQUESTS_TOTAL._labelnames) == {"method", "path", "status"}  # noqa: SLF001

    def test_http_request_duration_has_expected_labels(self) -> None:
        assert set(HTTP_REQUEST_DURATION_SECONDS._labelnames) == {"method", "path"}  # noqa: SLF001


class TestMakeCounter:
    def test_returns_counter_instance(self) -> None:
        registry = CollectorRegistry()
        counter = make_counter("test_orders_total", "Test orders", registry=registry)
        assert isinstance(counter, Counter)

    def test_counter_with_labels(self) -> None:
        registry = CollectorRegistry()
        counter = make_counter("test_labeled_total", "Labeled", ["status"], registry=registry)
        counter.labels(status="ok").inc()
        output = generate_latest(registry).decode()
        assert "test_labeled_total" in output

    def test_counter_without_labels(self) -> None:
        registry = CollectorRegistry()
        counter = make_counter("test_unlabeled_total", "No labels", registry=registry)
        counter.inc()
        output = generate_latest(registry).decode()
        assert "test_unlabeled_total" in output

    def test_counter_increments(self) -> None:
        registry = CollectorRegistry()
        counter = make_counter("test_increment_total", "Increment test", registry=registry)
        counter.inc(5)
        output = generate_latest(registry).decode()
        assert "5.0" in output


class TestMakeHistogram:
    def test_returns_histogram_instance(self) -> None:
        registry = CollectorRegistry()
        hist = make_histogram("test_latency_seconds", "Latency", registry=registry)
        assert isinstance(hist, Histogram)

    def test_histogram_with_custom_buckets(self) -> None:
        registry = CollectorRegistry()
        hist = make_histogram(
            "test_custom_bucket_seconds",
            "Custom buckets",
            buckets=(0.1, 0.5, 1.0),
            registry=registry,
        )
        hist.observe(0.3)
        output = generate_latest(registry).decode()
        assert "test_custom_bucket_seconds" in output

    def test_histogram_with_labels(self) -> None:
        registry = CollectorRegistry()
        hist = make_histogram(
            "test_hist_labeled_seconds", "Labeled hist", ["route"], registry=registry
        )
        hist.labels(route="/api/v1/health").observe(0.05)
        output = generate_latest(registry).decode()
        assert "test_hist_labeled_seconds" in output


class TestMakeGauge:
    def test_returns_gauge_instance(self) -> None:
        registry = CollectorRegistry()
        gauge = make_gauge("test_connections", "Active connections", registry=registry)
        assert isinstance(gauge, Gauge)

    def test_gauge_set_value(self) -> None:
        registry = CollectorRegistry()
        gauge = make_gauge("test_gauge_value", "Gauge value", registry=registry)
        gauge.set(42)
        output = generate_latest(registry).decode()
        assert "42.0" in output

    def test_gauge_with_labels(self) -> None:
        registry = CollectorRegistry()
        gauge = make_gauge("test_labeled_gauge", "Labeled gauge", ["broker"], registry=registry)
        gauge.labels(broker="kite").set(3)
        output = generate_latest(registry).decode()
        assert "test_labeled_gauge" in output


class TestGetMetricsOutput:
    def test_returns_bytes_and_content_type(self) -> None:
        content, media_type = get_metrics_output()
        assert isinstance(content, bytes)
        assert isinstance(media_type, str)
        assert "text/plain" in media_type

    def test_output_contains_http_requests_total(self) -> None:
        content, _ = get_metrics_output()
        assert b"http_requests_total" in content

    def test_output_contains_http_request_duration(self) -> None:
        content, _ = get_metrics_output()
        assert b"http_request_duration_seconds" in content
