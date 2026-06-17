"""Stage 5 — Spread Filter.

Rejects instruments with wide bid-ask spreads (spread_pct > max_spread_pct).
Instruments with no live quote (mid_price = 0, spread_pct = None) are also
excluded — stale spread = exclusion per AD-USE-01 failure modes.
"""

from __future__ import annotations

import logging

from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import SpreadConfig

_log = logging.getLogger(__name__)


def apply_spread_filter(
    instruments: list[InstrumentData],
    config: SpreadConfig,
) -> tuple[list[InstrumentData], dict[int, str]]:
    """Filter instruments by bid-ask spread threshold.

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
                "spread_excluded token=%d underlying=%s reason=%s",
                inst.instrument_token,
                inst.underlying,
                reason,
            )

    return passed, exclusions


def _check(inst: InstrumentData, config: SpreadConfig) -> str | None:
    sp = inst.spread_pct
    if sp is None:
        return "no_live_quote (bid=0 or ask=0)"
    if sp > config.max_spread_pct:
        return f"spread_pct={sp:.4f} > max_spread_pct={config.max_spread_pct}"
    return None
