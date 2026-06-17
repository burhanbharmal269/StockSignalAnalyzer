"""Stage 3 — Volume Ranker.

Ranks instruments by intraday volume relative to their own 20-day average
(volume_ratio = today_volume / avg_volume_20d). Instruments below
min_volume_ratio are excluded before ranking.
"""

from __future__ import annotations

import logging

from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import VolumeConfig

_log = logging.getLogger(__name__)


def apply_volume_filter(
    instruments: list[InstrumentData],
    config: VolumeConfig,
) -> tuple[list[InstrumentData], dict[int, str]]:
    """Filter by volume_ratio threshold and return survivors in descending rank order.

    Returns:
        (passed_sorted_desc, exclusions) where exclusions maps token → reason.
        passed_sorted_desc is sorted by volume_ratio descending.
    """
    passed: list[tuple[float, InstrumentData]] = []
    exclusions: dict[int, str] = {}

    for inst in instruments:
        ratio = inst.volume_ratio
        if ratio < config.min_volume_ratio:
            reason = (
                f"volume_ratio={ratio:.4f} < min_volume_ratio={config.min_volume_ratio}"
            )
            exclusions[inst.instrument_token] = reason
            _log.debug(
                "volume_excluded token=%d underlying=%s reason=%s",
                inst.instrument_token,
                inst.underlying,
                reason,
            )
        else:
            passed.append((ratio, inst))

    passed.sort(key=lambda t: t[0], reverse=True)
    return [inst for _, inst in passed], exclusions
