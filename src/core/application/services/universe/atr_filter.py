"""Stage 7 — ATR Filter.

Ensures sufficient intraday movement potential. Instruments with atr_14_pct
outside [min_atr_pct, max_atr_pct] are excluded.

If atr_14_pct is None (data unavailable from Feature Snapshot cache), the
instrument is EXCLUDED with a WARNING — this is a hard exclusion, not a
pass-through. ATR is required to compute composite score (AD-USE-01: Stage 8).
"""

from __future__ import annotations

import logging

from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import ATRConfig

_log = logging.getLogger(__name__)


def apply_atr_filter(
    instruments: list[InstrumentData],
    config: ATRConfig,
) -> tuple[list[InstrumentData], dict[int, str]]:
    """Filter instruments by ATR% range.

    Instruments with atr_14_pct=None are excluded (hard exclusion).

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
            if inst.atr_14_pct is None:
                _log.warning(
                    "atr_filter_excluded_no_data token=%d underlying=%s",
                    inst.instrument_token,
                    inst.underlying,
                )
            else:
                _log.debug(
                    "atr_excluded token=%d underlying=%s reason=%s",
                    inst.instrument_token,
                    inst.underlying,
                    reason,
                )

    return passed, exclusions


def _check(inst: InstrumentData, config: ATRConfig) -> str | None:
    if inst.atr_14_pct is None:
        return "atr_data_unavailable"
    if inst.atr_14_pct < config.min_atr_pct:
        return f"atr_14_pct={inst.atr_14_pct:.4f} < min_atr_pct={config.min_atr_pct}"
    if inst.atr_14_pct > config.max_atr_pct:
        return f"atr_14_pct={inst.atr_14_pct:.4f} > max_atr_pct={config.max_atr_pct}"
    return None
