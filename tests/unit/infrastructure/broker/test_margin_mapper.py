"""Unit tests for MarginMapper."""

from __future__ import annotations

from decimal import Decimal

from core.domain.value_objects.broker_dtos import BrokerMargin
from core.infrastructure.broker.margin_mapper import MarginMapper


def _margin(
    available: str = "80000",
    used: str = "20000",
    total: str = "100000",
    segment: str = "equity",
    exposure: str = "5000",
    span: str = "10000",
) -> BrokerMargin:
    return BrokerMargin(
        available_cash=Decimal(available),
        used_margin=Decimal(used),
        total_margin=Decimal(total),
        segment=segment,
        exposure_margin=Decimal(exposure),
        span_margin=Decimal(span),
    )


class TestMarginMapper:
    def test_to_account_state_fields_available_cash(self) -> None:
        fields = MarginMapper.to_account_state_fields(_margin(available="80000"))
        assert fields.available_cash == Decimal("80000")

    def test_to_account_state_fields_used_margin(self) -> None:
        fields = MarginMapper.to_account_state_fields(_margin(used="20000"))
        assert fields.used_margin == Decimal("20000")

    def test_to_account_state_fields_net_liquidation_value(self) -> None:
        fields = MarginMapper.to_account_state_fields(_margin(available="80000", used="20000"))
        # net = available + used = 100000
        assert fields.net_liquidation_value == Decimal("100000")

    def test_to_account_state_fields_segment(self) -> None:
        fields = MarginMapper.to_account_state_fields(_margin(segment="commodity"))
        assert fields.segment == "commodity"

    def test_to_account_state_fields_exposure_margin(self) -> None:
        fields = MarginMapper.to_account_state_fields(_margin(exposure="5000"))
        assert fields.exposure_margin == Decimal("5000")

    def test_to_account_state_fields_span_margin(self) -> None:
        fields = MarginMapper.to_account_state_fields(_margin(span="10000"))
        assert fields.span_margin == Decimal("10000")

    def test_to_dict_contains_all_keys(self) -> None:
        d = MarginMapper.to_dict(_margin())
        expected_keys = {
            "available_cash",
            "used_margin",
            "total_margin",
            "net_liquidation_value",
            "segment",
            "exposure_margin",
            "span_margin",
        }
        assert expected_keys == set(d.keys())

    def test_to_dict_values_are_decimal(self) -> None:
        d = MarginMapper.to_dict(_margin())
        for key, val in d.items():
            if key != "segment":
                assert isinstance(val, Decimal), f"{key} should be Decimal, got {type(val)}"
