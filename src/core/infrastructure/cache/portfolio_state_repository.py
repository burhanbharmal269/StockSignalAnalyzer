"""Redis implementation of IPortfolioStateRepository.

Reads:
  risk:portfolio_state    (Hash, TTL 60s)    → FAIL_CLOSED
  risk:graduated_response (Hash, no TTL)     → FAIL_CLOSED

Writes:
  risk:graduated_response (HSET, no TTL/EXPIRE) → set_graduated_response()

The Redis client must be configured with decode_responses=True.
"""

from __future__ import annotations

import json
from datetime import datetime

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.domain.exceptions.risk import DataSourceUnavailableError
from core.domain.interfaces.i_portfolio_state_repository import IPortfolioStateRepository
from core.domain.risk.graduated_response_state import _STATE_MULTIPLIER, GraduatedResponseState
from core.domain.risk.portfolio_state import PortfolioState

_PORT_KEY = "risk:portfolio_state"
_GRAD_KEY = "risk:graduated_response"
_PORT_SOURCE = "portfolio_state"
_GRAD_SOURCE = "graduated_response_state"

_PORT_REQUIRED: frozenset[str] = frozenset(
    {
        "open_positions_count",
        "positions_per_underlying",
        "capital_per_underlying_pct",
        "net_delta",
        "net_vega",
        "net_theta_daily",
        "orders_last_minute",
        "orders_today",
        "captured_at",
    }
)


def _fail(
    source: str, key: str, msg: str, exc: Exception | None = None
) -> DataSourceUnavailableError:
    err = DataSourceUnavailableError(source=source, message=f"{key}: {msg}")
    if exc is not None:
        err.__cause__ = exc
    return err


class RedisPortfolioStateRepository(IPortfolioStateRepository):

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def get_current(self) -> PortfolioState:
        try:
            raw: dict[str, str] = await self._redis.hgetall(_PORT_KEY)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise _fail(_PORT_SOURCE, _PORT_KEY, f"Redis unavailable: {exc}", exc) from exc

        if not raw:
            raise _fail(
                _PORT_SOURCE,
                _PORT_KEY,
                "key absent — PortfolioStatePoller has not written yet",
            )

        missing = _PORT_REQUIRED - raw.keys()
        if missing:
            raise _fail(_PORT_SOURCE, _PORT_KEY, f"missing required fields: {sorted(missing)}")

        try:
            positions_per_underlying: dict[str, int] = json.loads(
                raw["positions_per_underlying"]
            )
            capital_per_underlying_pct: dict[str, float] = json.loads(
                raw["capital_per_underlying_pct"]
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise _fail(
                _PORT_SOURCE, _PORT_KEY, f"JSON parse failure: {exc}", exc
            ) from exc

        try:
            return PortfolioState(
                open_positions_count=int(raw["open_positions_count"]),
                positions_per_underlying=positions_per_underlying,
                capital_per_underlying_pct=capital_per_underlying_pct,
                net_delta=float(raw["net_delta"]),
                net_vega=float(raw["net_vega"]),
                net_theta_daily=float(raw["net_theta_daily"]),
                orders_last_minute=int(raw["orders_last_minute"]),
                orders_today=int(raw["orders_today"]),
                captured_at=datetime.fromisoformat(raw["captured_at"]),
            )
        except (ValueError, TypeError) as exc:
            raise _fail(_PORT_SOURCE, _PORT_KEY, f"parse failure: {exc}", exc) from exc

    async def get_graduated_response(self) -> GraduatedResponseState:
        try:
            raw: dict[str, str] = await self._redis.hgetall(_GRAD_KEY)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise _fail(_GRAD_SOURCE, _GRAD_KEY, f"Redis unavailable: {exc}", exc) from exc

        if not raw:
            # Key absent at first startup — default to NORMAL
            return GraduatedResponseState(
                state="NORMAL",
                position_size_multiplier=1.0,
                activated_at=None,
                reason=None,
            )

        if "state" not in raw:
            raise _fail(_GRAD_SOURCE, _GRAD_KEY, "'state' field absent — corrupted hash")

        state = raw["state"]
        if state not in _STATE_MULTIPLIER:
            raise _fail(_GRAD_SOURCE, _GRAD_KEY, f"unrecognised state: {state!r}")

        activated_at: datetime | None = None
        raw_at = raw.get("activated_at", "")
        if raw_at:
            try:
                activated_at = datetime.fromisoformat(raw_at)
            except ValueError as exc:
                raise _fail(
                    _GRAD_SOURCE, _GRAD_KEY, f"malformed activated_at: {raw_at!r}", exc
                ) from exc

        return GraduatedResponseState(
            state=state,
            position_size_multiplier=_STATE_MULTIPLIER[state],
            activated_at=activated_at,
            reason=raw.get("reason") or None,
        )

    async def set_graduated_response(self, state: GraduatedResponseState) -> None:
        activated_at_str = (
            state.activated_at.isoformat() if state.activated_at is not None else ""
        )
        mapping: dict[str, str] = {
            "state": state.state,
            "position_size_multiplier": str(state.position_size_multiplier),
            "activated_at": activated_at_str,
            "reason": state.reason or "",
        }
        try:
            await self._redis.hset(_GRAD_KEY, mapping=mapping)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise _fail(_GRAD_SOURCE, _GRAD_KEY, f"Redis write failure: {exc}", exc) from exc
