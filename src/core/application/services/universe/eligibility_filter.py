"""Stage 1 — Instrument Eligibility Filter.

Removes instruments that are structurally ineligible for trading on the
current session date. This is the widest-mouth filter: it removes the
clearly ineligible before any market-data-dependent filters run.

Rules (all config-driven):
  - instrument_class must be in allowed_instrument_classes
  - dte must be >= 1 and <= max_dte_days
  - is_banned must be False when exclude_banned is True
"""

from __future__ import annotations

import logging

from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import EligibilityConfig

_log = logging.getLogger(__name__)


def apply_eligibility_filter(
    instruments: list[InstrumentData],
    config: EligibilityConfig,
) -> tuple[list[InstrumentData], dict[int, str]]:
    """Filter instruments by eligibility rules.

    Returns:
        (passed, exclusions) where exclusions maps instrument_token → reason.
    """
    allowed = frozenset(config.allowed_instrument_classes)
    passed: list[InstrumentData] = []
    exclusions: dict[int, str] = {}

    for inst in instruments:
        reason = _check(inst, allowed, config)
        if reason is None:
            passed.append(inst)
        else:
            exclusions[inst.instrument_token] = reason
            _log.debug(
                "eligibility_excluded token=%d underlying=%s reason=%s",
                inst.instrument_token,
                inst.underlying,
                reason,
            )

    return passed, exclusions


def _check(
    inst: InstrumentData,
    allowed: frozenset[str],
    config: EligibilityConfig,
) -> str | None:
    if inst.instrument_class not in allowed:
        return f"instrument_class={inst.instrument_class!r} not in allowed={sorted(allowed)}"
    if inst.dte < 1:
        return f"dte={inst.dte} < 1 (expired)"
    if inst.dte > config.max_dte_days:
        return f"dte={inst.dte} > max_dte_days={config.max_dte_days}"
    if config.exclude_banned and inst.is_banned:
        return "on_fno_ban_list"
    return None
