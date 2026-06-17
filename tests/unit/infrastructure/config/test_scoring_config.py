"""Unit tests for ScoringConfig loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from core.infrastructure.config.scoring_config import ScoringConfig, load_scoring_config


class TestLoadScoringConfig:
    def test_loads_real_config_file(self) -> None:
        config = load_scoring_config()
        assert config.version == "1.0"

    def test_total_max_score_is_100(self) -> None:
        config = load_scoring_config()
        assert config.total_max_score == 100

    def test_component_weights_sum_to_100(self) -> None:
        config = load_scoring_config()
        total = (
            config.components.oi_buildup.max_score
            + config.components.trend.max_score
            + config.components.option_chain.max_score
            + config.components.volume.max_score
            + config.components.vwap.max_score
            + config.components.sentiment.max_score
            + config.components.iv_analysis.max_score
        )
        assert total == 100

    def test_sha256_is_set(self) -> None:
        config = load_scoring_config()
        assert len(config.sha256) == 64
        assert all(c in "0123456789abcdef" for c in config.sha256)

    def test_sha256_is_deterministic(self) -> None:
        config1 = load_scoring_config()
        config2 = load_scoring_config()
        assert config1.sha256 == config2.sha256

    def test_execution_gate_values(self) -> None:
        config = load_scoring_config()
        assert config.execution_gate.min_score == 70
        assert config.execution_gate.min_confidence == 65

    def test_returns_scoring_config_instance(self) -> None:
        config = load_scoring_config()
        assert isinstance(config, ScoringConfig)

    def test_mismatched_weights_raises(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            version: "1.0"
            components:
              oi_buildup:
                max_score: 99
                description: "test"
              trend:
                max_score: 20
                description: "test"
              option_chain:
                max_score: 20
                description: "test"
              volume:
                max_score: 15
                description: "test"
              vwap:
                max_score: 10
                description: "test"
              sentiment:
                max_score: 5
                description: "test"
              iv_analysis:
                max_score: 5
                description: "test"
            total_max_score: 100
            execution_gate:
              min_score: 70
              min_confidence: 65
            thresholds:
              strong: 85
              standard: 70
              neutral: 50
              weak: 35
        """)
        config_file = tmp_path / "scoring.yaml"
        config_file.write_text(yaml_content)
        with pytest.raises(Exception):  # noqa: B017
            load_scoring_config(config_file)
