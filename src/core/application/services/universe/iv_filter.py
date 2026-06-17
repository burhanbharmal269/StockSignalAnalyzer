"""Stage 6 — IV Filter.

Selects instruments in a tradeable implied volatility regime.

If iv_pct or iv_rank is None (Phase 16+ data not yet available), this stage is
SKIPPED for that instrument (it passes through) with a WARNING logged.
This is the graceful degradation path documented in AD-USE-01 failure modes.
"""

from __future__ import annotations

import logging

from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import IVConfig

_log = logging.getLogger(__name__)


def apply_iv_filter(
    instruments: list[InstrumentData],
    config: IVConfig,
) -> tuple[list[InstrumentData], dict[int, str]]:
    """Filter instruments by IV% and IV rank thresholds.

    Instruments with iv_pct=None pass through (iv data unavailable → skip stage).

    Returns:
        (passed, exclusions) where exclusions maps instrument_token → reason.
    """
    passed: list[InstrumentData] = []
    exclusions: dict[int, str] = {}
    skipped_count = 0

    for inst in instruments:
        reason, skipped = _check(inst, config)
        if reason is None:
            passed.append(inst)
        else:
            if skipped:
                # IV data unavailable — pass through with warning
                passed.append(inst)
                skipped_count += 1
            else:
                exclusions[inst.instrument_token] = reason
                _log.debug(
                    "iv_excluded token=%d underlying=%s reason=%s",
                    inst.instrument_token,
                    inst.underlying,
                    reason,
                )

    if skipped_count:
        _log.warning(
            "iv_filter_skipped_for_%d_instruments (iv_pct=None)", skipped_count
        )

    return passed, exclusions


def _check(inst: InstrumentData, config: IVConfig) -> tuple[str | None, bool]:
    """Returns (reason, is_skipped). is_skipped=True means pass-through."""
    if inst.iv_pct is None:
        return "iv_data_unavailable", True

    if inst.iv_pct < config.min_iv_pct:
        return (
            f"iv_pct={inst.iv_pct:.2f} < min_iv_pct={config.min_iv_pct}",
            False,
        )
    if inst.iv_pct > config.max_iv_pct:
        return (
            f"iv_pct={inst.iv_pct:.2f} > max_iv_pct={config.max_iv_pct}",
            False,
        )

    if inst.iv_rank is not None:
        if inst.iv_rank < config.min_ivr:
            return (
                f"iv_rank={inst.iv_rank:.1f} < min_ivr={config.min_ivr}",
                False,
            )
        if inst.iv_rank > config.max_ivr:
            return (
                f"iv_rank={inst.iv_rank:.1f} > max_ivr={config.max_ivr}",
                False,
            )

    return None, False
