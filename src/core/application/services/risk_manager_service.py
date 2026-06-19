"""RiskManagerService — portfolio-level risk controls for the signal engine.

Checked ONCE per scan cycle (not per symbol). When any limit is breached,
the entire cycle is halted: no new signals are accepted. Monitoring continues.

Controls:
  daily_loss_limit_pct      — stop trading when today's realized losses exceed X%
                              (computed from pnl_pct on closed accepted signals today)
  max_consecutive_losses    — stop after N consecutive losses on accepted signals
  max_open_positions        — reject new signals when N positions are already open
  max_underlying_exposure_pct — reserved for live capital integration (config only)

When breached:
  - Returns (False, reason_string)
  - Logs risk_lock_triggered with the reason
  - Caller returns early; no signals processed this cycle

When clear:
  - Returns (True, None)
  - Normal signal generation proceeds

Fail-open design: any DB error during check returns (True, None) so a transient
DB issue never silently halts trading. Errors are logged as warnings.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)


class RiskManagerConfig:
    """Loaded from strategy.yaml risk_manager section."""

    def __init__(
        self,
        daily_loss_limit_pct: float = 3.0,
        max_consecutive_losses: int = 5,
        max_open_positions: int = 5,
        max_underlying_exposure_pct: float = 20.0,
        enabled: bool = True,
    ) -> None:
        self.daily_loss_limit_pct       = daily_loss_limit_pct
        self.max_consecutive_losses     = max_consecutive_losses
        self.max_open_positions         = max_open_positions
        self.max_underlying_exposure_pct = max_underlying_exposure_pct
        self.enabled                    = enabled


class RiskManagerService:
    """Portfolio-level risk controls evaluated once per scan cycle."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: RiskManagerConfig | None = None,
    ) -> None:
        self._sf  = session_factory
        self._cfg = config or RiskManagerConfig()

    async def check(self) -> tuple[bool, str | None]:
        """Return (allowed, reason). reason is None when trading is allowed.

        Fail-open: DB errors return (True, None) so a transient issue never
        silently halts the scan cycle.
        """
        if not self._cfg.enabled:
            return True, None

        try:
            return await self._evaluate()
        except Exception as exc:
            _log.warning("risk_manager.check_error — failing open: %s", exc)
            return True, None

    async def _evaluate(self) -> tuple[bool, str | None]:
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        async with self._sf() as db:
            # ── 1. Max open positions ──────────────────────────────────────
            r = await db.execute(
                text("""
                    SELECT COUNT(*) AS open_count
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND outcome IS NULL
                      AND created_at >= :today
                """),
                {"today": today_start},
            )
            open_count = int((r.fetchone() or (0,))[0] or 0)
            if open_count >= self._cfg.max_open_positions:
                reason = f"max_open_positions:{open_count}>={self._cfg.max_open_positions}"
                _log.warning("risk_manager.risk_lock_triggered reason=%s", reason)
                return False, reason

            # ── 2. Max consecutive losses ──────────────────────────────────
            r = await db.execute(
                text("""
                    SELECT outcome
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND outcome IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT :n
                """),
                {"n": self._cfg.max_consecutive_losses},
            )
            outcomes = [row[0] for row in r.fetchall()]
            if len(outcomes) >= self._cfg.max_consecutive_losses:
                consecutive = all(o == "LOSS" for o in outcomes)
                if consecutive:
                    reason = f"max_consecutive_losses:{self._cfg.max_consecutive_losses}"
                    _log.warning("risk_manager.risk_lock_triggered reason=%s", reason)
                    return False, reason

            # ── 3. Daily loss limit ────────────────────────────────────────
            r = await db.execute(
                text("""
                    SELECT COALESCE(SUM(
                        COALESCE(pnl_pct, current_return_pct)
                    ), 0) AS daily_pnl
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND outcome IS NOT NULL
                      AND outcome != 'OPEN'
                      AND created_at >= :today
                """),
                {"today": today_start},
            )
            daily_pnl = float((r.fetchone() or (0.0,))[0] or 0.0)
            if daily_pnl < -(self._cfg.daily_loss_limit_pct):
                reason = f"daily_loss_limit:{daily_pnl:.2f}%<=-{self._cfg.daily_loss_limit_pct}%"
                _log.warning("risk_manager.risk_lock_triggered reason=%s", reason)
                return False, reason

        return True, None

    async def get_status(self) -> dict:
        """Return current risk metrics for dashboard display."""
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          SUM(CASE WHEN outcome IS NULL THEN 1 ELSE 0 END) AS open_positions,
                          COALESCE(SUM(
                              CASE WHEN outcome IS NOT NULL AND outcome != 'OPEN'
                              THEN COALESCE(pnl_pct, current_return_pct) ELSE 0 END
                          ), 0) AS daily_pnl
                        FROM signal_analytics
                        WHERE was_accepted = true AND created_at >= :today
                    """),
                    {"today": today_start},
                )
                row = r.fetchone()
                open_pos  = int(row[0] or 0) if row else 0
                daily_pnl = float(row[1] or 0.0) if row else 0.0

                r2 = await db.execute(
                    text("""
                        SELECT outcome FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                        ORDER BY created_at DESC LIMIT :n
                    """),
                    {"n": self._cfg.max_consecutive_losses},
                )
                recent = [row[0] for row in r2.fetchall()]
                consecutive_losses = 0
                for o in recent:
                    if o == "LOSS":
                        consecutive_losses += 1
                    else:
                        break

            return {
                "enabled":                   self._cfg.enabled,
                "open_positions":            open_pos,
                "max_open_positions":        self._cfg.max_open_positions,
                "daily_pnl_pct":             round(daily_pnl, 4),
                "daily_loss_limit_pct":      self._cfg.daily_loss_limit_pct,
                "consecutive_losses":        consecutive_losses,
                "max_consecutive_losses":    self._cfg.max_consecutive_losses,
                "risk_locked":               (
                    open_pos >= self._cfg.max_open_positions
                    or consecutive_losses >= self._cfg.max_consecutive_losses
                    or daily_pnl <= -(self._cfg.daily_loss_limit_pct)
                ),
            }
        except Exception as exc:
            _log.warning("risk_manager.status_error: %s", exc)
            return {"enabled": self._cfg.enabled, "error": str(exc)}
