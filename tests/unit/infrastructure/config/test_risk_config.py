"""Unit tests for RiskConfig loader — v2.0 schema."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.infrastructure.config.risk_config import (
    RiskConfig,
    load_risk_config,
)

# ---------------------------------------------------------------------------
# Minimal valid v2.0 yaml for parameterised tests
# ---------------------------------------------------------------------------

_VALID_YAML = textwrap.dedent("""\
    version: "2.0"
    capital:
      total_capital: 500000
      risk_per_trade_pct: 1.0
    daily_loss:
      limit_pct: 2.0
      limit_abs: 10000
      graduated_response:
        reduce_size_at_pct: 50
        paper_mode_at_pct: 75
        kill_switch_at_pct: 100
    weekly_loss:
      limit_pct: 5.0
      limit_abs: 25000
    drawdown:
      max_drawdown_pct: 10.0
    position_limits:
      max_open_positions: 10
      max_positions_per_underlying: 3
      max_capital_per_underlying_pct: 20.0
      max_capital_per_sector_pct: 40.0
      max_notional_per_trade_pct: 10
    order_rate:
      max_orders_per_minute: 5
      max_orders_per_day: 50
    greeks:
      max_net_delta: 2500
      max_net_gamma_pct: 0.1
      max_net_vega_pct: 5.0
      max_theta_daily_decay_pct: 0.5
      max_age_seconds: 120
      new_position_grace_seconds: 90
      fallback_ttl_seconds: 300
    margin:
      utilization_limit_pct: 80
      min_free_margin_pct: 20
      timeout_ms: 150
    risk_reward:
      min_ratio: 1.5
      max_ratio: 10.0
    position_sizing:
      method: "atr_kelly"
      kelly_fraction: 0.25
      atr_period: 14
      atr_stop_multiplier: 1.5
      max_position_size_lots: 50
      min_kelly_samples: 30
      kelly_min_sample_fallback: 0.05
    db:
      risk_decisions_insert_timeout_ms: 100
    redis_fail_safe:
      account_state: FAIL_CLOSED
      portfolio_state: FAIL_CLOSED
      graduated_response_state: FAIL_CLOSED
      greeks_cache:
        policy: FAIL_CLOSED
        fallback_ttl_seconds: 300
      correlation_matrix:
        policy: CONSERVATIVE_DEFAULT
        default_correlation: 1.0
      margin_required: FAIL_CLOSED
    risk_engine:
      gather_timeout_ms: 500
    dead_mans_switch:
      redis_check_interval_seconds: 30
      redis_failure_threshold: 3
      db_check_interval_seconds: 30
      db_failure_threshold: 3
""")


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "risk.yaml"
    p.write_text(content)
    return p


class TestLoadRealConfig:
    def test_loads_real_config_file(self) -> None:
        config = load_risk_config()
        assert config.version == "2.0"

    def test_returns_risk_config_instance(self) -> None:
        config = load_risk_config()
        assert isinstance(config, RiskConfig)

    def test_version_is_2_0(self) -> None:
        config = load_risk_config()
        assert config.version == "2.0"


class TestCapitalSection:
    def test_risk_per_trade_pct_is_valid(self) -> None:
        config = load_risk_config()
        assert 0.0 <= config.capital.risk_per_trade_pct <= 100.0

    def test_total_capital_positive(self) -> None:
        config = load_risk_config()
        assert config.capital.total_capital >= 1


class TestDailyLossSection:
    def test_daily_loss_limit_pct_positive(self) -> None:
        config = load_risk_config()
        assert config.daily_loss.limit_pct > 0.0

    def test_daily_loss_limit_abs_positive(self) -> None:
        config = load_risk_config()
        assert config.daily_loss.limit_abs > 0

    def test_graduated_response_has_three_tiers(self) -> None:
        config = load_risk_config()
        gr = config.daily_loss.graduated_response
        assert gr.reduce_size_at_pct < gr.paper_mode_at_pct
        assert gr.paper_mode_at_pct <= gr.kill_switch_at_pct


class TestWeeklyLossSection:
    def test_weekly_loss_fields_present(self) -> None:
        config = load_risk_config()
        assert config.weekly_loss.limit_pct > 0.0
        assert config.weekly_loss.limit_abs > 0


class TestPositionLimitsSection:
    def test_max_open_positions(self) -> None:
        config = load_risk_config()
        assert config.position_limits.max_open_positions >= 1

    def test_max_positions_per_underlying(self) -> None:
        config = load_risk_config()
        assert config.position_limits.max_positions_per_underlying >= 1

    def test_notional_cap_present(self) -> None:
        config = load_risk_config()
        assert 0.0 < config.position_limits.max_notional_per_trade_pct <= 100.0


class TestGreeksSection:
    def test_greeks_fields_present(self) -> None:
        config = load_risk_config()
        assert config.greeks.max_net_delta > 0
        assert config.greeks.max_net_vega_pct > 0

    def test_cache_seconds_positive(self) -> None:
        config = load_risk_config()
        assert config.greeks.max_age_seconds >= 1
        assert config.greeks.new_position_grace_seconds >= 0
        assert config.greeks.fallback_ttl_seconds >= 1


class TestMarginSection:
    def test_margin_fields_present(self) -> None:
        config = load_risk_config()
        assert 0.0 < config.margin.utilization_limit_pct <= 100.0
        assert 0.0 < config.margin.min_free_margin_pct <= 100.0

    def test_margin_timeout_ms_positive(self) -> None:
        config = load_risk_config()
        assert config.margin.timeout_ms >= 1

    def test_margin_timeout_seconds_property(self) -> None:
        config = load_risk_config()
        assert config.margin.timeout_seconds == pytest.approx(config.margin.timeout_ms / 1000.0)


class TestRiskEngineSection:
    def test_gather_timeout_ms_positive(self) -> None:
        config = load_risk_config()
        assert config.risk_engine.gather_timeout_ms >= 1

    def test_gather_timeout_seconds_property(self) -> None:
        config = load_risk_config()
        assert config.risk_engine.gather_timeout_seconds == pytest.approx(
            config.risk_engine.gather_timeout_ms / 1000.0
        )


class TestDeadMansSwitchSection:
    def test_intervals_positive(self) -> None:
        config = load_risk_config()
        assert config.dead_mans_switch.redis_check_interval_seconds >= 1
        assert config.dead_mans_switch.db_check_interval_seconds >= 1

    def test_thresholds_positive(self) -> None:
        config = load_risk_config()
        assert config.dead_mans_switch.redis_failure_threshold >= 1
        assert config.dead_mans_switch.db_failure_threshold >= 1


class TestPositionSizingSection:
    def test_method_is_valid(self) -> None:
        config = load_risk_config()
        assert config.position_sizing.method in {"atr_kelly", "fixed_fractional", "fixed_lots"}

    def test_kelly_protection_fields_present(self) -> None:
        config = load_risk_config()
        assert config.position_sizing.max_position_size_lots >= 1
        assert config.position_sizing.min_kelly_samples >= 1
        assert 0.0 <= config.position_sizing.kelly_min_sample_fallback <= 1.0


class TestDbSection:
    def test_insert_timeout_ms_positive(self) -> None:
        config = load_risk_config()
        assert config.db.risk_decisions_insert_timeout_ms >= 1

    def test_insert_timeout_seconds_property(self) -> None:
        config = load_risk_config()
        expected = config.db.risk_decisions_insert_timeout_ms / 1000.0
        assert config.db.risk_decisions_insert_timeout_seconds == pytest.approx(expected)


class TestRedisFailSafeSection:
    def test_fail_safe_policies_present(self) -> None:
        config = load_risk_config()
        assert config.redis_fail_safe.account_state == "FAIL_CLOSED"
        assert config.redis_fail_safe.portfolio_state == "FAIL_CLOSED"
        assert config.redis_fail_safe.graduated_response_state == "FAIL_CLOSED"
        assert config.redis_fail_safe.margin_required == "FAIL_CLOSED"

    def test_greeks_cache_fail_safe(self) -> None:
        config = load_risk_config()
        assert config.redis_fail_safe.greeks_cache.policy == "FAIL_CLOSED"
        assert config.redis_fail_safe.greeks_cache.fallback_ttl_seconds >= 1

    def test_correlation_matrix_conservative_default(self) -> None:
        config = load_risk_config()
        cm = config.redis_fail_safe.correlation_matrix
        assert cm.policy == "CONSERVATIVE_DEFAULT"
        assert cm.default_correlation == 1.0


class TestValidation:
    def test_invalid_version_raises(self, tmp_path: Path) -> None:
        content = _VALID_YAML.replace('version: "2.0"', 'version: "1.0"')
        path = _write_yaml(tmp_path, content)
        with pytest.raises(Exception, match="2.0"):
            load_risk_config(path)

    def test_invalid_position_sizing_method_raises(self, tmp_path: Path) -> None:
        content = _VALID_YAML.replace('method: "atr_kelly"', 'method: "invalid_method"')
        path = _write_yaml(tmp_path, content)
        with pytest.raises(ValidationError):
            load_risk_config(path)

    def test_valid_yaml_loads_successfully(self, tmp_path: Path) -> None:
        path = _write_yaml(tmp_path, _VALID_YAML)
        config = load_risk_config(path)
        assert config.version == "2.0"
        assert config.capital.total_capital == 500000

    def test_invalid_fail_safe_policy_raises(self, tmp_path: Path) -> None:
        content = _VALID_YAML.replace(
            "account_state: FAIL_CLOSED",
            "account_state: IGNORE",
        )
        path = _write_yaml(tmp_path, content)
        with pytest.raises(ValidationError):
            load_risk_config(path)
