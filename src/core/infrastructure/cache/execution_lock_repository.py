"""Redis implementation of the Execution Lock repository.

Stores the execution lock state at key ``system:execution_lock`` (Redis Hash).

Fields:
    locked          — "true" | "false"
    execution_mode  — "MANUAL" | "AUTOMATIC"
    changed_at      — ISO-8601 datetime
    changed_by      — free-text actor identifier
    note            — free-text reason

Invariants:
    - Key absent → default UNLOCKED + MANUAL (safe: signals always flow, orders blocked)
    - No TTL — the lock is persistent across restarts
    - HGETALL is the only read operation
    - HSET is the only write operation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.domain.exceptions.risk import DataSourceUnavailableError

_KEY = "system:execution_lock"
_SOURCE = "execution_lock"

_VALID_MODES = frozenset({"MANUAL", "AUTOMATIC"})


@dataclass(frozen=True)
class ExecutionLockState:
    locked: bool
    execution_mode: str          # "MANUAL" | "AUTOMATIC"
    changed_at: datetime | None
    changed_by: str | None
    note: str | None

    @property
    def is_order_blocked(self) -> bool:
        """Orders are blocked when LOCKED or in MANUAL mode."""
        return self.locked or self.execution_mode == "MANUAL"


class RedisExecutionLockRepository:
    """Reads and writes the system:execution_lock Redis Hash."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def get_state(self) -> ExecutionLockState:
        try:
            raw: dict[str, str] = await self._redis.hgetall(_KEY)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"Redis unavailable reading {_KEY}: {exc}",
            ) from exc

        if not raw:
            return ExecutionLockState(
                locked=False,
                execution_mode="MANUAL",
                changed_at=None,
                changed_by=None,
                note=None,
            )

        locked_raw = raw.get("locked", "false")
        if locked_raw == "true":
            locked = True
        elif locked_raw == "false":
            locked = False
        else:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"{_KEY}.locked has unrecognised value: {locked_raw!r}",
            )

        mode = raw.get("execution_mode", "MANUAL").upper()
        if mode not in _VALID_MODES:
            mode = "MANUAL"

        changed_at: datetime | None = None
        raw_dt = raw.get("changed_at", "")
        if raw_dt:
            try:
                changed_at = datetime.fromisoformat(raw_dt)
            except ValueError:
                changed_at = None

        return ExecutionLockState(
            locked=locked,
            execution_mode=mode,
            changed_at=changed_at,
            changed_by=raw.get("changed_by") or None,
            note=raw.get("note") or None,
        )

    async def set_locked(self, locked: bool, by: str, note: str = "") -> None:
        try:
            await self._redis.hset(
                _KEY,
                mapping={
                    "locked": "true" if locked else "false",
                    "changed_at": datetime.now(UTC).isoformat(),
                    "changed_by": by,
                    "note": note,
                },
            )
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"Redis unavailable writing {_KEY}: {exc}",
            ) from exc

    async def set_mode(self, mode: str, by: str) -> None:
        mode_upper = mode.upper()
        if mode_upper not in _VALID_MODES:
            raise ValueError(f"Invalid execution_mode: {mode!r}")
        try:
            await self._redis.hset(
                _KEY,
                mapping={
                    "execution_mode": mode_upper,
                    "changed_at": datetime.now(UTC).isoformat(),
                    "changed_by": by,
                    "note": f"execution_mode changed to {mode_upper}",
                },
            )
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"Redis unavailable writing {_KEY}: {exc}",
            ) from exc

    async def seed_if_absent(self, default_mode: str = "MANUAL") -> bool:
        """Seed the key with safe defaults only if it does not exist yet.

        Returns True if seeded, False if already present.
        """
        try:
            exists = await self._redis.exists(_KEY)
            if exists:
                return False
            await self._redis.hset(
                _KEY,
                mapping={
                    "locked": "false",
                    "execution_mode": default_mode.upper(),
                    "changed_at": datetime.now(UTC).isoformat(),
                    "changed_by": "startup_seed",
                    "note": f"Initial seed: execution_mode={default_mode.upper()}, locked=false",
                },
            )
            return True
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"Redis unavailable seeding {_KEY}: {exc}",
            ) from exc
