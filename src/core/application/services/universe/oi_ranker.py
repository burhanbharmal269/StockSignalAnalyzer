"""Stage 4 — Open Interest Ranker.

Ranks by near-ATM open interest. Instruments with atm_oi below min_oi_lots
are excluded. Survivors are sorted by atm_oi descending.
"""

from __future__ import annotations

import logging

from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import OIConfig

_log = logging.getLogger(__name__)


def apply_oi_filter(
    instruments: list[InstrumentData],
    config: OIConfig,
) -> tuple[list[InstrumentData], dict[int, str]]:
    """Filter by minimum near-ATM OI and return survivors sorted descending by OI.

    Returns:
        (passed_sorted_desc, exclusions) where exclusions maps token → reason.
    """
    passed: list[tuple[float, InstrumentData]] = []
    exclusions: dict[int, str] = {}

    for inst in instruments:
        if inst.atm_oi < config.min_oi_lots:
            reason = (
                f"atm_oi={inst.atm_oi:.0f} < min_oi_lots={config.min_oi_lots}"
            )
            exclusions[inst.instrument_token] = reason
            _log.debug(
                "oi_excluded token=%d underlying=%s reason=%s",
                inst.instrument_token,
                inst.underlying,
                reason,
            )
        else:
            passed.append((inst.atm_oi, inst))

    passed.sort(key=lambda t: t[0], reverse=True)
    return [inst for _, inst in passed], exclusions
