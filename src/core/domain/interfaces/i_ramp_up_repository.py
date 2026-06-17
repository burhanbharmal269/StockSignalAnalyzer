"""IRampUpRepository — port for live trading ramp-up state persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.application.services.live_trading_safety_service import RampUpState


class IRampUpRepository(ABC):
    @abstractmethod
    async def get_current(self) -> RampUpState | None:
        """Return the current (most recent) ramp-up state, or None if not initialized."""

    @abstractmethod
    async def create_initial(self) -> RampUpState:
        """Insert Stage 1 ramp-up state and return it."""

    @abstractmethod
    async def promote_stage(self, performance_snapshot: dict) -> RampUpState:
        """Advance to the next stage and return updated state."""

    @abstractmethod
    async def lock(self, reason: str) -> None:
        """Lock trading; record lock_reason."""

    @abstractmethod
    async def unlock(self) -> None:
        """Remove the trading lock."""
