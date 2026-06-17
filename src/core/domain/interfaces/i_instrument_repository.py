"""IInstrumentRepository — domain port for instrument master persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.domain.entities.instrument import Instrument
from core.domain.value_objects.symbol import Symbol


class IInstrumentRepository(ABC):
    @abstractmethod
    async def save(self, instrument: Instrument) -> None:
        """Persist or update an instrument."""

    @abstractmethod
    async def save_bulk(self, instruments: list[Instrument]) -> None:
        """Upsert a batch of instruments (used during master refresh)."""

    @abstractmethod
    async def get_by_token(self, token: int) -> Instrument | None:
        """Return instrument by broker instrument token."""

    @abstractmethod
    async def get_by_symbol(self, symbol: Symbol) -> Instrument | None:
        """Return instrument by ticker + exchange."""

    @abstractmethod
    async def get_active_fno(self) -> list[Instrument]:
        """Return all active FnO instruments."""

    @abstractmethod
    async def count_active(self) -> int:
        """Return the total count of active instruments across all segments."""

    @abstractmethod
    async def get_all_tokens(self) -> set[int]:
        """Return the set of all persisted instrument tokens (active + inactive)."""
