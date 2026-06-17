"""Unit tests for signal fingerprint computation."""

from __future__ import annotations

from core.domain.value_objects.signal_fingerprint import compute_signal_fingerprint


class TestSignalFingerprint:
    def test_returns_64_char_hex(self) -> None:
        fp = compute_signal_fingerprint(
            "TRENDING_BULLISH", 82, "LONG", ("oi_buildup", "trend"), 14.5
        )
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_deterministic_same_inputs(self) -> None:
        args = ("SIDEWAYS", 75.5, "SHORT", ("volume", "vwap"), 18.2)
        assert compute_signal_fingerprint(*args) == compute_signal_fingerprint(*args)

    def test_different_regime_different_fingerprint(self) -> None:
        fp1 = compute_signal_fingerprint(
            "TRENDING_BULLISH", 82, "LONG", ("oi_buildup", "trend"), 14.5
        )
        fp2 = compute_signal_fingerprint(
            "TRENDING_BEARISH", 82, "LONG", ("oi_buildup", "trend"), 14.5
        )
        assert fp1 != fp2

    def test_different_direction_different_fingerprint(self) -> None:
        fp1 = compute_signal_fingerprint("SIDEWAYS", 75, "LONG", ("oi_buildup", "trend"), 14.5)
        fp2 = compute_signal_fingerprint("SIDEWAYS", 75, "SHORT", ("oi_buildup", "trend"), 14.5)
        assert fp1 != fp2

    def test_top2_order_independent(self) -> None:
        fp1 = compute_signal_fingerprint(
            "TRENDING_BULLISH", 82, "LONG", ("oi_buildup", "trend"), 14.5
        )
        fp2 = compute_signal_fingerprint(
            "TRENDING_BULLISH", 82, "LONG", ("trend", "oi_buildup"), 14.5
        )
        assert fp1 == fp2

    def test_score_bucket_70_and_79_same(self) -> None:
        fp1 = compute_signal_fingerprint("SIDEWAYS", 70, "LONG", ("oi_buildup", "trend"), 14.5)
        fp2 = compute_signal_fingerprint("SIDEWAYS", 79, "LONG", ("oi_buildup", "trend"), 14.5)
        assert fp1 == fp2

    def test_score_bucket_standard_and_strong_different(self) -> None:
        # STANDARD: 70–84, STRONG: >= 85 — different buckets → different fingerprint
        fp1 = compute_signal_fingerprint("SIDEWAYS", 70, "LONG", ("oi_buildup", "trend"), 14.5)
        fp2 = compute_signal_fingerprint("SIDEWAYS", 85, "LONG", ("oi_buildup", "trend"), 14.5)
        assert fp1 != fp2

    def test_vix_bucket_low(self) -> None:
        # Both in "<14" bucket: 12.0 and 13.9
        fp1 = compute_signal_fingerprint("SIDEWAYS", 75, "LONG", ("oi_buildup", "trend"), 12.0)
        fp2 = compute_signal_fingerprint("SIDEWAYS", 75, "LONG", ("oi_buildup", "trend"), 13.9)
        assert fp1 == fp2

    def test_vix_bucket_high_vs_elevated_differ(self) -> None:
        # 20.0 → "18-22", 25.0 → ">22" → different buckets
        fp1 = compute_signal_fingerprint("SIDEWAYS", 75, "LONG", ("oi_buildup", "trend"), 25.0)
        fp2 = compute_signal_fingerprint("SIDEWAYS", 75, "LONG", ("oi_buildup", "trend"), 20.0)
        assert fp1 != fp2
