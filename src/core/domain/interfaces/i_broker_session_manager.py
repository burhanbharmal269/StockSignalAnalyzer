"""IBrokerSessionManager — domain port for broker session lifecycle."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.entities.broker_session import BrokerSession


class IBrokerSessionManager(ABC):
    """Orchestrates the full broker session lifecycle.

    Implementations handle create/refresh/validate/terminate across
    any IBroker adapter. The application layer depends only on this
    interface; no broker SDK types appear here.
    """

    @abstractmethod
    async def create_session(
        self,
        api_key: str,
        request_token: str,
        api_secret: str,
    ) -> BrokerSession:
        """Authenticate with the broker and persist the encrypted session.

        Raises:
            BrokerAuthenticationError: On invalid credentials.
        """

    @abstractmethod
    async def refresh_session(self, session: BrokerSession) -> BrokerSession:
        """Obtain a fresh session, deactivating *session* if successful.

        Used when the current session is about to expire (e.g. daily Kite token).

        Raises:
            BrokerAuthenticationError: If re-authentication fails.
        """

    @abstractmethod
    async def validate_session(self, session: BrokerSession) -> bool:
        """Return True if *session* is active, unexpired, and broker-reachable."""

    @abstractmethod
    async def terminate_session(self, session: BrokerSession) -> None:
        """Log out at the broker and deactivate the session in the repository."""
