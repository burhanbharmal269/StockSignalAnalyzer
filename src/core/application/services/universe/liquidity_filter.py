"""Stage 2 — Liquidity Filter.

Removes instruments with insufficient market depth to support entry and exit
without undue slippage. Two independent thresholds must both be met.

Rules:
  - avg_traded_value_5d >= min_liquidity_crores (INR crore)
  - active_strikes_count >= min_active_strikes
"""

from __future__ import annotations

import logging

from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import LiquidityConfig

_log = logging.getLogger(__name__)


def apply_liquidity_filter(
    instruments: list[InstrumentData],
    config: LiquidityConfig,
) -> tuple[list[InstrumentData], dict[int, str]]:
    """Filter instruments by liquidity thresholds.

    Returns:
        (passed, exclusions) where exclusions maps instrument_token → reason.
    """
    passed: list[InstrumentData] = []
    exclusions: dict[int, str] = {}

    for inst in instruments:
        reason = _check(inst, config)
        if reason is None:
            passed.append(inst)
        else:
            exclusions[inst.instrument_token] = reason
            _log.debug(
                "liquidity_excluded token=%d underlying=%s reason=%s",
                inst.instrument_token,
                inst.underlying,
                reason,
            )

    return passed, exclusions


def _check(inst: InstrumentData, config: LiquidityConfig) -> str | None:
    if inst.avg_traded_value_5d < config.min_liquidity_crores:
        return (
            f"avg_traded_value_5d={inst.avg_traded_value_5d:.2f} < "
            f"min_liquidity_crores={config.min_liquidity_crores}"
        )
    if inst.active_strikes_count < config.min_active_strikes:
        return (
            f"active_strikes_count={inst.active_strikes_count} < "
            f"min_active_strikes={config.min_active_strikes}"
        )
    return None
