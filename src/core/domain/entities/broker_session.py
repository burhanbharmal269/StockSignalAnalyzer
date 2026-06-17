"""BrokerSession entity — authenticated broker session with encrypted token.

The encrypted_access_token field stores the AES-256-GCM ciphertext produced
by TokenEncryptor. The plaintext access token is never persisted anywhere.

Reference: docs/23_SECURITY_BASELINE.md §1.1 Broker Access Token Encryption
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class BrokerSession:
    """An active broker authentication session.

    Invariants:
        - encrypted_access_token is always non-empty (set at creation).
        - expires_at is UTC-aware.
        - Once deactivated, is_active cannot be set to True again.
    """

    session_id: uuid.UUID
    broker_name: str
    api_key: str
    encrypted_access_token: str
    expires_at: datetime
    is_active: bool = field(default=True)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    user_name: str = field(default="")

    def is_expired(self) -> bool:
        """Return True if the token expiry time has passed."""
        return datetime.now(UTC) >= self.expires_at

    def deactivate(self) -> None:
        """Mark the session as inactive (e.g. on logout or token expiry)."""
        self.is_active = False

    @classmethod
    def create(
        cls,
        broker_name: str,
        api_key: str,
        encrypted_access_token: str,
        expires_at: datetime,
        user_name: str = "",
    ) -> BrokerSession:
        """Factory method — always use this to create new sessions."""
        return cls(
            session_id=uuid.uuid4(),
            broker_name=broker_name,
            api_key=api_key,
            encrypted_access_token=encrypted_access_token,
            expires_at=expires_at,
            user_name=user_name,
        )
