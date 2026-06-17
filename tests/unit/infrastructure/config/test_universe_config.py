"""Unit tests for UniverseConfig loading and validation."""

from __future__ import annotations

import pytest

from core.infrastructure.config.universe_config import load_universe_config


class TestLoadUniverseConfig:
    def test_loads_successfully(self) -> None:
        cfg = load_universe_config()
        assert cfg.enabled is True
        assert cfg.max_candidates == 20
        assert cfg.evaluation_interval_seconds == 300

    def test_weights_sum_to_one(self) -> None:
        cfg = load_universe_config()
        total = (
            cfg.volume.weight
            + cfg.oi.weight
            + cfg.spread.weight
            + cfg.atr.weight
        )
        assert abs(total - 1.0) < 1e-6

    def test_eligibility_classes_set(self) -> None:
        cfg = load_universe_config()
        assert "OPTION" in cfg.eligibility.allowed_instrument_classes
        assert cfg.eligibility.max_dte_days >= 1

    def test_diversification_loaded(self) -> None:
        cfg = load_universe_config()
        assert cfg.diversification.enabled is True
        assert cfg.diversification.max_per_sector >= 1

    def test_cache_ttl_is_interval_plus_60(self) -> None:
        cfg = load_universe_config()
        assert cfg.cache_ttl_seconds == cfg.evaluation_interval_seconds + 60


class TestWeightValidation:
    def test_weights_not_summing_to_one_raises(self) -> None:
        from pydantic import ValidationError
        from core.infrastructure.config.universe_config import UniverseConfig
        import yaml
        from pathlib import Path

        raw = yaml.safe_load(
            (Path(__file__).parents[4] / "config" / "universe.yaml").read_text()
        )
        # Corrupt a weight
        raw["universe"]["volume"]["weight"] = 0.99
        with pytest.raises(ValidationError, match="weights must sum to 1.0"):
            UniverseConfig.model_validate(raw["universe"])

    def test_iv_max_less_than_min_raises(self) -> None:
        from pydantic import ValidationError
        from core.infrastructure.config.universe_config import UniverseConfig
        import yaml
        from pathlib import Path

        raw = yaml.safe_load(
            (Path(__file__).parents[4] / "config" / "universe.yaml").read_text()
        )
        raw["universe"]["iv"]["min_iv_pct"] = 90.0
        raw["universe"]["iv"]["max_iv_pct"] = 10.0
        with pytest.raises(ValidationError):
            UniverseConfig.model_validate(raw["universe"])
