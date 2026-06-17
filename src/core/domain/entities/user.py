"""User domain entity.

Represents an authenticated operator of the platform. The hashed_password
field holds an Argon2id hash — never plain text. The domain layer does not
depend on the hashing implementation; verification happens in the application
layer via PasswordService.

The force_change flag is set True by the first-run initializer and cleared
after the operator changes the generated password (Doc 23 §2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.domain.enums.user_role import UserRole


@dataclass(frozen=True)
class User:
    user_id: str
    username: str
    hashed_password: str
    role: UserRole
    is_active: bool
    force_change: bool
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_login_at: datetime | None = None
