"""Unit tests for SignalFingerprint."""

from __future__ import annotations

import pytest

from core.domain.value_objects.signal_fingerprint import SignalFingerprint


def _fp(**kwargs: object) -> SignalFingerprint:
    defaults = {
        "regime": "TRENDING_BULLISH",
        "score_bucket": "STANDARD",
        "direction": "LONG",
        "top_2_components": ("OI_BUILDUP", "TREND"),
        "vix_bucket": "14-18",
    }
    defaults.update(kwargs)  # type: ignore[arg-type]
    return SignalFingerprint(**defaults)  # type: ignore[arg-type]


class TestSignalFingerprintDeterminism:
    def test_same_inputs_same_sha256(self) -> None:
        a = _fp()
        b = _fp()
        assert a.sha256 == b.sha256

    def test_sha256_is_64_hex_chars(self) -> None:
        fp = _fp()
        assert len(fp.sha256) == 64
        assert all(c in "0123456789abcdef" for c in fp.sha256)

    def test_different_regime_different_sha256(self) -> None:
        a = _fp(regime="TRENDING_BULLISH")
        b = _fp(regime="TRENDING_BEARISH")
        assert a.sha256 != b.sha256

    def test_different_direction_different_sha256(self) -> None:
        a = _fp(direction="LONG")
        b = _fp(direction="SHORT")
        assert a.sha256 != b.sha256

    def test_different_score_bucket_different_sha256(self) -> None:
        a = _fp(score_bucket="STRONG")
        b = _fp(score_bucket="STANDARD")
        assert a.sha256 != b.sha256

    def test_different_top_2_components_different_sha256(self) -> None:
        a = _fp(top_2_components=("OI_BUILDUP", "TREND"))
        b = _fp(top_2_components=("VOLUME", "VWAP"))
        assert a.sha256 != b.sha256

    def test_different_vix_bucket_different_sha256(self) -> None:
        a = _fp(vix_bucket="<14")
        b = _fp(vix_bucket=">22")
        assert a.sha256 != b.sha256

    def test_top_2_components_order_does_not_matter(self) -> None:
        a = _fp(top_2_components=("OI_BUILDUP", "TREND"))
        b = _fp(top_2_components=("TREND", "OI_BUILDUP"))
        assert a.sha256 == b.sha256

    def test_invalid_score_bucket_raises(self) -> None:
        with pytest.raises(ValueError, match="score_bucket"):
            _fp(score_bucket="WEAK")

    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            _fp(direction="NEUTRAL")

    def test_invalid_vix_bucket_raises(self) -> None:
        with pytest.raises(ValueError, match="vix_bucket"):
            _fp(vix_bucket="99-100")

    def test_vix_bucket_for_none(self) -> None:
        assert SignalFingerprint.vix_bucket_for(None) == "unknown"

    def test_vix_bucket_for_low(self) -> None:
        assert SignalFingerprint.vix_bucket_for(12.5) == "<14"

    def test_vix_bucket_for_mid(self) -> None:
        assert SignalFingerprint.vix_bucket_for(16.0) == "14-18"

    def test_vix_bucket_for_high(self) -> None:
        assert SignalFingerprint.vix_bucket_for(20.0) == "18-22"

    def test_vix_bucket_for_extreme(self) -> None:
        assert SignalFingerprint.vix_bucket_for(25.0) == ">22"

    def test_score_bucket_for_strong(self) -> None:
        assert SignalFingerprint.score_bucket_for(90.0) == "STRONG"
        assert SignalFingerprint.score_bucket_for(85.0) == "STRONG"

    def test_score_bucket_for_standard(self) -> None:
        assert SignalFingerprint.score_bucket_for(84.9) == "STANDARD"
        assert SignalFingerprint.score_bucket_for(70.0) == "STANDARD"

    def test_unknown_vix_bucket_valid(self) -> None:
        fp = _fp(vix_bucket="unknown")
        assert len(fp.sha256) == 64
