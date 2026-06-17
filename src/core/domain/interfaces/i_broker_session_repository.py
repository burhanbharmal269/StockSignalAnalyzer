"""IBrokerSessionRepository — domain port for persisting broker sessions.

Reference: docs/23_SECURITY_BASELINE.md §1.1 Broker Access Token Encryption
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.entities.broker_session import BrokerSession


class IBrokerSessionRepository(ABC):
    """Persistence port for BrokerSession entities.

    Sessions are stored with the encrypted_access_token; the plaintext token
    is never written to the database.
    """

    @abstractmethod
    async def save(self, session: BrokerSession) -> None:
        """Insert or update a broker session."""

    @abstractmethod
    async def get_active(self, broker_name: str) -> BrokerSession | None:
        """Return the current active session for *broker_name*, or None."""

    @abstractmethod
    async def get_by_id(self, session_id: uuid.UUID) -> BrokerSession | None:
        """Return a session by its UUID, or None if not found."""

    @abstractmethod
    async def deactivate_all(self, broker_name: str) -> None:
        """Mark all sessions for *broker_name* as inactive."""
