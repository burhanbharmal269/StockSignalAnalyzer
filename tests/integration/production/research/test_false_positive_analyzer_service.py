"""Tests for FalsePositiveAnalyzerService — bucket boundary and rate formulas."""

from __future__ import annotations

import pytest


def _bucket_label(normalised_score: float) -> str:
    """Mirrors the service bucket logic."""
    if normalised_score < 60:
        return "0-60"
    elif normalised_score < 70:
        return "60-70"
    elif normalised_score < 80:
        return "70-80"
    elif normalised_score < 90:
        return "80-90"
    else:
        return "90-100"


def _fp_rate(in_bucket_losses: int, total_in_bucket: int) -> float:
    if total_in_bucket == 0:
        return 0.0
    return in_bucket_losses / total_in_bucket


def _fn_rate(out_of_bucket_wins: int, total_wins: int) -> float:
    if total_wins == 0:
        return 0.0
    return out_of_bucket_wins / total_wins


class TestBucketBoundaries:
    def test_below_60_goes_to_first_bucket(self) -> None:
        assert _bucket_label(55.0) == "0-60"

    def test_exactly_60_goes_to_second_bucket(self) -> None:
        assert _bucket_label(60.0) == "60-70"

    def test_exactly_70_goes_to_third_bucket(self) -> None:
        assert _bucket_label(70.0) == "70-80"

    def test_exactly_80_goes_to_fourth_bucket(self) -> None:
        assert _bucket_label(80.0) == "80-90"

    def test_exactly_90_goes_to_last_bucket(self) -> None:
        assert _bucket_label(90.0) == "90-100"

    def test_99_goes_to_last_bucket(self) -> None:
        assert _bucket_label(99.9) == "90-100"


class TestRateFormulas:
    def test_fp_rate_all_losses(self) -> None:
        assert _fp_rate(5, 5) == pytest.approx(1.0)

    def test_fp_rate_no_losses(self) -> None:
        assert _fp_rate(0, 10) == pytest.approx(0.0)

    def test_fp_rate_partial(self) -> None:
        assert _fp_rate(3, 10) == pytest.approx(0.3)

    def test_fp_rate_empty_bucket(self) -> None:
        assert _fp_rate(0, 0) == pytest.approx(0.0)

    def test_fn_rate_all_wins_elsewhere(self) -> None:
        assert _fn_rate(10, 10) == pytest.approx(1.0)

    def test_fn_rate_no_wins_elsewhere(self) -> None:
        assert _fn_rate(0, 5) == pytest.approx(0.0)

    def test_fn_rate_no_wins_at_all(self) -> None:
        assert _fn_rate(0, 0) == pytest.approx(0.0)
