"""Redis implementation of IKillSwitchRepository.

Reads and writes the system:kill_switch Redis Hash.

Invariants enforced here:
- HGETALL is the only read operation (never GET or HGET).
- HSET is the only write operation.
- EXPIRE and PEXPIRE are never called — the Hash has no TTL.
- Empty HGETALL (key absent) → default inactive state, not an error.
- Non-empty HGETALL without is_active field → DataSourceUnavailableError (RC-3).
- is_active value not exactly "true" or "false" → DataSourceUnavailableError (RC-3).
- Malformed datetime string in any field → DataSourceUnavailableError (RC-4).
- Redis ConnectionError or TimeoutError → DataSourceUnavailableError (FAIL_CLOSED).
"""

from __future__ import annotations

from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.domain.exceptions.risk import DataSourceUnavailableError
from core.domain.interfaces.i_kill_switch_repository import IKillSwitchRepository
from core.domain.risk.kill_switch_state import KillSwitchState

_KEY = "system:kill_switch"
_SOURCE = "kill_switch"


def _parse_optional_dt(value: str, field: str) -> datetime | None:
    """Parse an ISO 8601 string to datetime, or return None for empty strings.

    Raises DataSourceUnavailableError (RC-4) on any parse failure so that
    corrupted hash fields never surface as raw ValueError to callers.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise DataSourceUnavailableError(
            source=_SOURCE,
            message=f"{_KEY}.{field} contains malformed datetime: {value!r}",
        ) from exc


class RedisKillSwitchRepository(IKillSwitchRepository):
    """Redis Hash implementation of IKillSwitchRepository.

    The Redis client must be configured with decode_responses=True so that
    HGETALL returns dict[str, str] rather than dict[bytes, bytes].
    """

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def get_state(self) -> KillSwitchState:
        try:
            raw: dict[str, str] = await self._redis.hgetall(_KEY)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"Redis unavailable while reading {_KEY}: {exc}",
            ) from exc

        if not raw:
            # Key absent — first-ever startup — return the safe default state.
            return KillSwitchState(
                is_active=False,
                activated_at=None,
                activated_by=None,
                activation_reason=None,
                deactivated_at=None,
                deactivated_by=None,
                deactivation_note=None,
            )

        # RC-3: a present hash without is_active is corrupted — FAIL_CLOSED.
        if "is_active" not in raw:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=(
                    f"{_KEY} hash exists but 'is_active' field is absent — "
                    "corrupted hash, treating as kill switch active"
                ),
            )

        raw_is_active = raw["is_active"]
        if raw_is_active == "true":
            is_active = True
        elif raw_is_active == "false":
            is_active = False
        else:
            # RC-3: reject any value that is not exactly "true" or "false".
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=(
                    f"{_KEY}.is_active has unrecognised value: {raw_is_active!r} "
                    "(expected 'true' or 'false')"
                ),
            )

        # RC-4: all datetime fields are protected from raw ValueError.
        activated_at = _parse_optional_dt(raw.get("activated_at", ""), "activated_at")
        deactivated_at = _parse_optional_dt(raw.get("deactivated_at", ""), "deactivated_at")

        return KillSwitchState(
            is_active=is_active,
            activated_at=activated_at,
            activated_by=raw.get("activated_by") or None,
            activation_reason=raw.get("activation_reason") or None,
            deactivated_at=deactivated_at,
            deactivated_by=raw.get("deactivated_by") or None,
            deactivation_note=raw.get("deactivation_note") or None,
        )

    async def activate(
        self,
        reason: str,
        activated_by: str,
        trigger_source: str,
    ) -> None:
        try:
            await self._redis.hset(
                _KEY,
                mapping={
                    "is_active": "true",
                    "activated_at": datetime.now(UTC).isoformat(),
                    "activated_by": activated_by,
                    "activation_reason": reason,
                    "trigger_source": trigger_source,
                    "deactivated_at": "",
                    "deactivated_by": "",
                    "deactivation_note": "",
                },
            )
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"Redis unavailable during {_KEY} activation: {exc}",
            ) from exc

    async def deactivate(
        self,
        deactivated_by: str,
        note: str,
        override_loss_check: bool = False,
    ) -> None:
        try:
            await self._redis.hset(
                _KEY,
                mapping={
                    "is_active": "false",
                    "deactivated_at": datetime.now(UTC).isoformat(),
                    "deactivated_by": deactivated_by,
                    "deactivation_note": note,
                },
            )
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"Redis unavailable during {_KEY} deactivation: {exc}",
            ) from exc
