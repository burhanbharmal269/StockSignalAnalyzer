"""Unit tests for Exchange, Segment, InstrumentType, and OptionType enums."""

from __future__ import annotations

import pytest

from core.domain.enums.exchange import Exchange
from core.domain.enums.instrument_type import InstrumentType
from core.domain.enums.option_type import OptionType
from core.domain.enums.segment import Segment


class TestExchange:
    def test_all_values_are_str_enum(self) -> None:
        for member in Exchange:
            assert isinstance(member.value, str)

    def test_nse_value(self) -> None:
        assert Exchange.NSE == "NSE"

    def test_nfo_value(self) -> None:
        assert Exchange.NFO == "NFO"

    def test_roundtrip(self) -> None:
        assert Exchange("BSE") is Exchange.BSE

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            Exchange("INVALID")


class TestSegment:
    def test_nse_fo_value(self) -> None:
        assert Segment.NSE_FO == "NSE_FO"

    def test_bse_eq_value(self) -> None:
        assert Segment.BSE_EQ == "BSE_EQ"

    def test_roundtrip(self) -> None:
        assert Segment("MCX_FO") is Segment.MCX_FO

    def test_all_segments_defined(self) -> None:
        expected = {"NSE_EQ", "BSE_EQ", "NSE_FO", "BSE_FO", "MCX_FO", "CDS_FO"}
        assert {s.value for s in Segment} == expected


class TestInstrumentType:
    def test_ce_value(self) -> None:
        assert InstrumentType.CE == "CE"

    def test_pe_value(self) -> None:
        assert InstrumentType.PE == "PE"

    def test_fut_value(self) -> None:
        assert InstrumentType.FUT == "FUT"

    def test_eq_value(self) -> None:
        assert InstrumentType.EQ == "EQ"

    def test_index_value(self) -> None:
        assert InstrumentType.INDEX == "INDEX"


class TestOptionType:
    def test_ce_value(self) -> None:
        assert OptionType.CE == "CE"

    def test_pe_value(self) -> None:
        assert OptionType.PE == "PE"

    def test_roundtrip(self) -> None:
        assert OptionType("CE") is OptionType.CE
        assert OptionType("PE") is OptionType.PE

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            OptionType("OTM")
