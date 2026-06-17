"""SignalConfig — Pydantic model for config/signal.yaml.

Loaded once at startup via load_signal_config(). All application layer
components that need signal configuration receive this object via DI.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator, model_validator


class SignalGateConfig(BaseModel):
    min_score: int = 70
    min_confidence: int = 65

    @field_validator("min_score", "min_confidence")
    @classmethod
    def _must_be_positive(cls, v: int) -> int:
        if v < 0 or v > 100:
            raise ValueError(f"Gate threshold must be in [0, 100], got {v}")
        return v


class SignalRedisConfig(BaseModel):
    dedup_key_prefix: str = "signal:dedup"
    active_key_prefix: str = "signal:active"


_VALID_EXECUTION_MODES = frozenset({"MANUAL", "AUTOMATIC"})


class SignalConfig(BaseModel):
    ttl_minutes: int = 15
    market_close_time: str = "15:15:00"
    dedup_ttl_minutes: int = 30
    gate: SignalGateConfig = SignalGateConfig()
    redis: SignalRedisConfig = SignalRedisConfig()
    execution_mode: str = "MANUAL"  # MANUAL | AUTOMATIC

    @field_validator("execution_mode")
    @classmethod
    def _valid_execution_mode(cls, v: str) -> str:
        v = v.upper()
        if v not in _VALID_EXECUTION_MODES:
            raise ValueError(f"execution_mode must be one of {_VALID_EXECUTION_MODES}, got {v!r}")
        return v

    @property
    def is_manual_mode(self) -> bool:
        return self.execution_mode == "MANUAL"

    @property
    def is_automatic_mode(self) -> bool:
        return self.execution_mode == "AUTOMATIC"

    @field_validator("ttl_minutes", "dedup_ttl_minutes")
    @classmethod
    def _must_be_positive_minutes(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"TTL minutes must be >= 1, got {v}")
        return v

    @model_validator(mode="after")
    def _dedup_longer_than_ttl(self) -> SignalConfig:
        if self.dedup_ttl_minutes < self.ttl_minutes:
            raise ValueError(
                f"dedup_ttl_minutes ({self.dedup_ttl_minutes}) must be >= "
                f"ttl_minutes ({self.ttl_minutes})"
            )
        return self

    @property
    def ttl_seconds(self) -> int:
        return self.ttl_minutes * 60

    @property
    def dedup_ttl_seconds(self) -> int:
        return self.dedup_ttl_minutes * 60

    def dedup_key(
        self,
        instrument_token: int,
        direction: str,
        strategy_type: str,
        regime: str,
        weights_sha256: str,
    ) -> str:
        """Build a dedup key that distinguishes strategy and regime.

        Including strategy_type and regime prevents NIFTY LONG Trend and
        NIFTY LONG MeanReversion from being treated as the same signal.
        Key: signal:dedup:{token}:{direction}:{strategy}:{regime}:{weights_sha256}
        """
        return (
            f"{self.redis.dedup_key_prefix}"
            f":{instrument_token}:{direction}:{strategy_type}:{regime}:{weights_sha256}"
        )

    def active_key(self, instrument_token: int) -> str:
        return f"{self.redis.active_key_prefix}:{instrument_token}"


class _SignalYaml(BaseModel):
    version: str
    signal: SignalConfig


def load_signal_config(
    path: Path | None = None,
) -> SignalConfig:
    """Load and validate config/signal.yaml.

    Args:
        path: Override path for testing. Defaults to <project_root>/config/signal.yaml.
    """
    if path is None:
        path = Path(__file__).parents[4] / "config" / "signal.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    wrapper = _SignalYaml.model_validate(raw)
    return wrapper.signal
