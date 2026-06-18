"""AccountStateSeeder — writes default account state to Redis if the key is missing.

The Risk Engine reads `risk:account_state` (HGETALL) and raises
DataSourceUnavailableError when the key is absent, rejecting every signal with
no audit trail.  This seeder runs once at startup and writes safe defaults so
the Risk Engine can function immediately.

The seeded values represent a clean paper-trading session:
  - Full capital available (from risk.yaml total_capital)
  - Zero P&L
  - Zero loss consumed
  - PAPER trading_mode

The real AccountStatePoller (when implemented) will overwrite these fields with
live broker margin data.  The seed is idempotent — it does nothing if the key
already has data.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

_log = logging.getLogger(__name__)

_ACCT_KEY = "risk:account_state"
_PORT_KEY  = "risk:portfolio_state"
_TTL_SECONDS = 86_400  # 24 h — enough for a full trading day


class AccountStateSeeder:
    """Seeds `risk:account_state` in Redis with paper-trading defaults."""

    def __init__(self, redis_client, risk_config) -> None:
        self._redis = redis_client
        self._config = risk_config

    async def seed_if_missing(self) -> bool:
        """Write defaults for account + portfolio state if either key is absent.

        Returns True if at least one key was seeded.
        """
        seeded = False
        seeded |= await self._seed_account_state()
        seeded |= await self._seed_portfolio_state()
        return seeded

    async def _seed_account_state(self) -> bool:
        """Seed risk:account_state, always syncing capital from risk.yaml.

        Capital fields (account_capital, session_capital) are always written from
        risk.yaml so that changing total_capital takes effect on next restart.
        P&L and utilisation fields are only written when the key is entirely absent
        (fresh session) — live intraday state is preserved across restarts.
        """
        try:
            existing = await self._redis.hgetall(_ACCT_KEY)
        except Exception as exc:
            _log.error("account_state_seeder.redis_error: %s", exc)
            return False

        capital  = str(self._config.capital.total_capital)
        now_iso  = datetime.now(UTC).isoformat()

        if existing:
            # Key exists — only update capital fields from risk.yaml.
            # Preserve live P&L / margin utilisation to survive restarts.
            try:
                await self._redis.hset(_ACCT_KEY, mapping={
                    "account_capital": capital,
                    "session_capital": capital,
                    "captured_at": now_iso,
                })
                await self._redis.expire(_ACCT_KEY, _TTL_SECONDS)
            except Exception as exc:
                _log.error("account_state_seeder.account_update_error: %s", exc)
                return False
            _log.info(
                "account_state_seeder.capital_synced capital=%s trading_mode=%s",
                capital, existing.get("trading_mode", "?"),
            )
            return True

        # Fresh key — write all fields with safe paper-trading defaults.
        state: dict[str, str] = {
            "account_capital": capital,
            "session_capital": capital,
            "available_margin": capital,
            "used_margin": "0",
            "margin_utilization_pct": "0.0",
            "daily_pnl": "0",
            "daily_loss_consumed_pct": "0.0",
            "weekly_pnl": "0",
            "weekly_loss_consumed_pct": "0.0",
            "drawdown_from_hwm_pct": "0.0",
            "open_positions_count": "0",
            "position_size_multiplier": "1.0",
            "trading_mode": "PAPER",
            "captured_at": now_iso,
        }

        try:
            await self._redis.hset(_ACCT_KEY, mapping=state)
            await self._redis.expire(_ACCT_KEY, _TTL_SECONDS)
        except Exception as exc:
            _log.error("account_state_seeder.account_write_error: %s", exc)
            return False

        _log.info("account_state_seeder.account_seeded capital=%s trading_mode=PAPER", capital)
        return True

    async def _seed_portfolio_state(self) -> bool:
        """Seed risk:portfolio_state if absent. Returns True if seeded."""
        import json as _json

        try:
            existing = await self._redis.hgetall(_PORT_KEY)
        except Exception as exc:
            _log.error("account_state_seeder.portfolio_redis_error: %s", exc)
            return False

        if existing:
            _log.info(
                "account_state_seeder.portfolio_already_present open=%s",
                existing.get("open_positions_count", "?"),
            )
            return False

        now_iso = datetime.now(UTC).isoformat()

        state: dict[str, str] = {
            "open_positions_count": "0",
            "positions_per_underlying": _json.dumps({}),
            "capital_per_underlying_pct": _json.dumps({}),
            "net_delta": "0.0",
            "net_vega": "0.0",
            "net_theta_daily": "0.0",
            "orders_last_minute": "0",
            "orders_today": "0",
            "captured_at": now_iso,
        }

        try:
            await self._redis.hset(_PORT_KEY, mapping=state)
            await self._redis.expire(_PORT_KEY, _TTL_SECONDS)
        except Exception as exc:
            _log.error("account_state_seeder.portfolio_write_error: %s", exc)
            return False

        _log.info("account_state_seeder.portfolio_seeded open_positions=0")
        return True
