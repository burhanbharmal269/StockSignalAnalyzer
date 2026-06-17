"""IUserRepository — domain interface for user persistence.

Only the domain operations required by Phase 6 auth are declared here.
All implementations live in the infrastructure layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from core.domain.entities.user import User


class IUserRepository(ABC):
    @abstractmethod
    async def find_by_username(self, username: str) -> User | None:
        """Return the User matching username, or None."""

    @abstractmethod
    async def find_by_id(self, user_id: str) -> User | None:
        """Return the User matching user_id (UUID string), or None."""

    @abstractmethod
    async def create(self, user: User) -> None:
        """Persist a new User record."""

    @abstractmethod
    async def update_password(
        self, user_id: str, hashed_password: str, force_change: bool
    ) -> None:
        """Replace the stored hashed password and reset force_change flag."""

    @abstractmethod
    async def update_last_login(self, user_id: str, timestamp: datetime) -> None:
        """Record the last successful login timestamp."""

    @abstractmethod
    async def has_any_admin(self) -> bool:
        """Return True if at least one admin user exists (for first-run detection)."""
