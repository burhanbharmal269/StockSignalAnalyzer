"""Unit tests for UniverseSelected domain event."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from core.domain.events.universe_events import UniverseSelected
from core.domain.universe.selected_instrument import SelectedInstrument


def _make_instrument(token: int = 1001, rank: int = 1) -> SelectedInstrument:
    return SelectedInstrument(
        instrument_token=token,
        underlying="NIFTY",
        instrument_class="OPTION",
        expiry_date=date(2026, 6, 26),
        sector="Index",
        composite_score=0.75,
        rank=rank,
    )


class TestUniverseSelectedDefaults:
    def test_default_fields(self) -> None:
        event = UniverseSelected()
        assert event.instruments == ()
        assert event.total_eligible == 0
        assert event.total_filtered_out == 0
        assert event.evaluation_cycle_ms == 0
        assert event.protected_count == 0
        assert event.universe_enabled is True

    def test_has_event_id(self) -> None:
        event = UniverseSelected()
        assert isinstance(event.event_id, uuid.UUID)

    def test_event_type(self) -> None:
        event = UniverseSelected()
        assert event.event_type == "UniverseSelected"


class TestUniverseSelectedWithInstruments:
    def test_instruments_stored_as_tuple(self) -> None:
        inst = _make_instrument()
        event = UniverseSelected(instruments=(inst,), total_eligible=5)
        assert len(event.instruments) == 1
        assert event.instruments[0].instrument_token == 1001

    def test_disabled_universe(self) -> None:
        event = UniverseSelected(universe_enabled=False, total_filtered_out=10)
        assert not event.universe_enabled
        assert event.total_filtered_out == 10

    def test_immutable(self) -> None:
        event = UniverseSelected()
        with pytest.raises((AttributeError, TypeError)):
            event.total_eligible = 99  # type: ignore[misc]
