"""Redis implementation of IAccountStateRepository.

Reads the risk:account_state Redis Hash (HGETALL).
FAIL_CLOSED on any Redis error, missing key, or parse failure.

Key schema (all string values):
  account_capital, session_capital, available_margin, used_margin — Decimal strings
  margin_utilization_pct, daily_loss_consumed_pct, weekly_loss_consumed_pct,
  drawdown_from_hwm_pct, position_size_multiplier                — float strings
  open_positions_count                                            — int string
  daily_pnl, weekly_pnl                                          — Decimal strings
  trading_mode                                                    — "LIVE"|"PAPER"|"BLOCKED"
  captured_at                                                     — ISO 8601 UTC
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.domain.exceptions.risk import DataSourceUnavailableError
from core.domain.interfaces.i_account_state_repository import IAccountStateRepository
from core.domain.risk.account_state import AccountState

_KEY = "risk:account_state"
_SOURCE = "account_state"

_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "account_capital",
        "session_capital",
        "available_margin",
        "used_margin",
        "margin_utilization_pct",
        "daily_pnl",
        "daily_loss_consumed_pct",
        "weekly_pnl",
        "weekly_loss_consumed_pct",
        "drawdown_from_hwm_pct",
        "open_positions_count",
        "position_size_multiplier",
        "trading_mode",
        "captured_at",
    }
)


def _parse_decimal(raw: str, field: str) -> Decimal:
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise DataSourceUnavailableError(
            source=_SOURCE,
            message=f"{_KEY}.{field} is not a valid Decimal: {raw!r}",
        ) from exc


def _parse_float(raw: str, field: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise DataSourceUnavailableError(
            source=_SOURCE,
            message=f"{_KEY}.{field} is not a valid float: {raw!r}",
        ) from exc


def _parse_int(raw: str, field: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise DataSourceUnavailableError(
            source=_SOURCE,
            message=f"{_KEY}.{field} is not a valid int: {raw!r}",
        ) from exc


def _parse_dt(raw: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DataSourceUnavailableError(
            source=_SOURCE,
            message=f"{_KEY}.{field} is not a valid ISO datetime: {raw!r}",
        ) from exc


class RedisAccountStateRepository(IAccountStateRepository):
    """HGETALL-based reader for the risk:account_state Redis Hash.

    The Redis client must be configured with decode_responses=True.
    """

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def get_current(self) -> AccountState:
        try:
            raw: dict[str, str] = await self._redis.hgetall(_KEY)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"Redis unavailable reading {_KEY}: {exc}",
            ) from exc

        if not raw:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"{_KEY} key is absent — AccountStatePoller has not written yet",
            )

        missing = _REQUIRED_FIELDS - raw.keys()
        if missing:
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"{_KEY} hash is missing required fields: {sorted(missing)}",
            )

        try:
            return AccountState(
                account_capital=_parse_decimal(raw["account_capital"], "account_capital"),
                session_capital=_parse_decimal(raw["session_capital"], "session_capital"),
                available_margin=_parse_decimal(raw["available_margin"], "available_margin"),
                used_margin=_parse_decimal(raw["used_margin"], "used_margin"),
                margin_utilization_pct=_parse_float(
                    raw["margin_utilization_pct"], "margin_utilization_pct"
                ),
                daily_pnl=_parse_decimal(raw["daily_pnl"], "daily_pnl"),
                daily_loss_consumed_pct=_parse_float(
                    raw["daily_loss_consumed_pct"], "daily_loss_consumed_pct"
                ),
                weekly_pnl=_parse_decimal(raw["weekly_pnl"], "weekly_pnl"),
                weekly_loss_consumed_pct=_parse_float(
                    raw["weekly_loss_consumed_pct"], "weekly_loss_consumed_pct"
                ),
                drawdown_from_hwm_pct=_parse_float(
                    raw["drawdown_from_hwm_pct"], "drawdown_from_hwm_pct"
                ),
                open_positions_count=_parse_int(
                    raw["open_positions_count"], "open_positions_count"
                ),
                position_size_multiplier=_parse_float(
                    raw["position_size_multiplier"], "position_size_multiplier"
                ),
                trading_mode=raw["trading_mode"],
                captured_at=_parse_dt(raw["captured_at"], "captured_at"),
            )
        except (DataSourceUnavailableError, Exception) as exc:
            if isinstance(exc, DataSourceUnavailableError):
                raise
            raise DataSourceUnavailableError(
                source=_SOURCE,
                message=f"Failed to construct AccountState from {_KEY}: {exc}",
            ) from exc
