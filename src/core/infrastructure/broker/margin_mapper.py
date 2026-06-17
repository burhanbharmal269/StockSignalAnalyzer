"""MarginMapper — translates BrokerMargin to AccountState-compatible fields.

The AccountState lives in the Risk Engine (Phase 13). This mapper extracts
the fields AccountState needs without introducing a cross-layer import.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.broker_dtos import BrokerMargin


@dataclass(frozen=True)
class AccountStateFields:
    """Fields extracted from BrokerMargin for AccountState hydration."""

    available_cash: Decimal
    used_margin: Decimal
    total_margin: Decimal
    net_liquidation_value: Decimal
    segment: str
    exposure_margin: Decimal
    span_margin: Decimal


class MarginMapper:
    """Stateless mapper: BrokerMargin → AccountStateFields."""

    @staticmethod
    def to_account_state_fields(margin: BrokerMargin) -> AccountStateFields:
        return AccountStateFields(
            available_cash=margin.available_cash,
            used_margin=margin.used_margin,
            total_margin=margin.total_margin,
            net_liquidation_value=margin.available_cash + margin.used_margin,
            segment=margin.segment,
            exposure_margin=margin.exposure_margin,
            span_margin=margin.span_margin,
        )

    @staticmethod
    def to_dict(margin: BrokerMargin) -> dict:
        """Flat dict suitable for passing to AccountState.update()."""
        fields = MarginMapper.to_account_state_fields(margin)
        return {
            "available_cash": fields.available_cash,
            "used_margin": fields.used_margin,
            "total_margin": fields.total_margin,
            "net_liquidation_value": fields.net_liquidation_value,
            "segment": fields.segment,
            "exposure_margin": fields.exposure_margin,
            "span_margin": fields.span_margin,
        }
