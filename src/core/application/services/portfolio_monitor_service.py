"""PortfolioMonitorService — monitors portfolio health and manages HWM + graduated response.

Runs as a supervised background task (every 30s cycle).

Responsibilities:
1. Read account state from Redis
2. Update global HWM (risk:hwm — no date suffix, never resets, D-10)
3. Apply graduated response transitions based on daily_loss_consumed_pct
4. Publish portfolio events (DailyLossLimitBreached, DrawdownLimitBreached, etc.)
5. Activate kill switch when daily_loss_consumed_pct >= kill_switch_at_pct

Graduated response (D-10):
  NORMAL  (×1.0) → REDUCED (×0.5) at reduce_size_at_pct
  REDUCED (×0.5) → PAPER   (×0.0) at paper_mode_at_pct
  PAPER   (×0.0) → KILLED          at kill_switch_at_pct (triggers kill switch)

HWM rule (D-10):
  risk:hwm = String key, no TTL, never resets daily.
  Updated when account.account_capital > current_hwm.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.application.services.kill_switch_service import KillSwitchService
from core.domain.events.risk_events import (
    DailyLossLimitBreached,
    DrawdownLimitBreached,
    GraduatedResponseActivated,
    HighWaterMarkUpdated,
    MarginAlertBreached,
    PaperModeActivated,
    WeeklyLossLimitBreached,
)
from core.domain.interfaces.i_account_state_repository import IAccountStateRepository
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_portfolio_state_repository import IPortfolioStateRepository
from core.domain.risk.graduated_response_state import GraduatedResponseState
from core.infrastructure.config.risk_config import RiskConfig

_log = logging.getLogger(__name__)

_HWM_KEY = "risk:hwm"
_CYCLE_SECONDS = 30


class PortfolioMonitorService:

    def __init__(
        self,
        account_state_repo: IAccountStateRepository,
        portfolio_state_repo: IPortfolioStateRepository,
        kill_switch_service: KillSwitchService,
        event_bus: IEventBus,
        redis_client: Redis,
        config: RiskConfig,
    ) -> None:
        self._account_repo = account_state_repo
        self._portfolio_repo = portfolio_state_repo
        self._ks_service = kill_switch_service
        self._event_bus = event_bus
        self._redis = redis_client
        self._config = config

    async def run(self) -> None:
        """Continuous monitoring loop.  Runs until cancelled."""
        _log.info("portfolio_monitor_service started")
        while True:
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception("portfolio_monitor_cycle_error")
            await asyncio.sleep(_CYCLE_SECONDS)

    async def _run_cycle(self) -> None:
        try:
            account = await self._account_repo.get_current()
        except Exception:
            _log.warning("portfolio_monitor: account_state unavailable — skipping cycle")
            return

        # HWM update
        await self._maybe_update_hwm(float(account.account_capital))

        # Graduated response transitions
        try:
            grad = await self._portfolio_repo.get_graduated_response()
        except Exception:
            _log.warning("portfolio_monitor: graduated_response unavailable — skipping transitions")
            grad = None

        if grad is not None:
            await self._apply_graduated_response(account.daily_loss_consumed_pct, grad)

        # Drawdown
        max_dd = self._config.drawdown.max_drawdown_pct
        if account.drawdown_from_hwm_pct >= max_dd:
            await self._event_bus.publish(
                DrawdownLimitBreached(
                    current_drawdown_pct=account.drawdown_from_hwm_pct,
                    limit_pct=max_dd,
                )
            )
            _log.critical(
                "portfolio_monitor.drawdown_limit_breached pct=%.1f limit=%.1f (auto-activation disabled)",
                account.drawdown_from_hwm_pct, max_dd,
            )

        # Weekly loss
        if account.weekly_loss_consumed_pct >= 100.0:
            await self._event_bus.publish(
                WeeklyLossLimitBreached(
                    current_loss_pct=account.weekly_loss_consumed_pct,
                    limit_pct=self._config.weekly_loss.limit_pct,
                    rolling_days=5,
                )
            )

        # Margin alert
        margin_limit = self._config.margin.utilization_limit_pct
        if account.margin_utilization_pct >= margin_limit:
            await self._event_bus.publish(
                MarginAlertBreached(
                    available_margin=float(account.available_margin),
                    used_margin=float(account.used_margin),
                    utilization_pct=account.margin_utilization_pct,
                    limit_pct=margin_limit,
                    instrument_token=None,
                )
            )

    async def _maybe_update_hwm(self, current_capital: float) -> None:
        try:
            raw: str | None = await self._redis.get(_HWM_KEY)
            current_hwm = float(raw) if raw is not None else 0.0
        except (RedisConnectionError, RedisTimeoutError):
            _log.warning("portfolio_monitor: failed to read HWM from Redis")
            return
        except (TypeError, ValueError):
            current_hwm = 0.0

        if current_capital > current_hwm:
            try:
                await self._redis.set(_HWM_KEY, str(current_capital))
            except (RedisConnectionError, RedisTimeoutError):
                _log.warning("portfolio_monitor: failed to write HWM to Redis")
                return
            if current_hwm > 0:
                await self._event_bus.publish(
                    HighWaterMarkUpdated(
                        previous_hwm=current_hwm,
                        new_hwm=current_capital,
                        updated_at=datetime.now(UTC),
                    )
                )

    async def _apply_graduated_response(
        self, daily_loss_pct: float, current_grad: GraduatedResponseState
    ) -> None:
        cfg = self._config.daily_loss.graduated_response
        current_state = current_grad.state

        # Determine target tier
        if daily_loss_pct >= cfg.kill_switch_at_pct:
            target_state = "KILLED"
        elif daily_loss_pct >= cfg.paper_mode_at_pct:
            target_state = "PAPER"
        elif daily_loss_pct >= cfg.reduce_size_at_pct:
            target_state = "REDUCED"
        else:
            target_state = "NORMAL"

        state_order = ["NORMAL", "REDUCED", "PAPER", "KILLED"]

        if state_order.index(target_state) <= state_order.index(current_state):
            return

        now = datetime.now(UTC)
        multiplier_map = {"NORMAL": 1.0, "REDUCED": 0.5, "PAPER": 0.0, "KILLED": 0.0}
        new_state = GraduatedResponseState(
            state=target_state,
            position_size_multiplier=multiplier_map[target_state],
            activated_at=now,
            reason=f"daily_loss_pct={daily_loss_pct:.1f}% triggered {target_state}",
        )

        try:
            await self._portfolio_repo.set_graduated_response(new_state)
        except Exception:
            _log.error(
                "portfolio_monitor: failed to persist graduated_response state=%s",
                target_state,
                exc_info=True,
            )
            return

        await self._event_bus.publish(
            GraduatedResponseActivated(
                state=target_state,
                daily_loss_pct=daily_loss_pct,
                position_size_multiplier=multiplier_map[target_state],
            )
        )

        if target_state == "PAPER":
            await self._event_bus.publish(
                PaperModeActivated(
                    daily_loss_pct=daily_loss_pct,
                    paper_mode_at_pct=cfg.paper_mode_at_pct,
                    activated_at=now,
                )
            )

        if daily_loss_pct >= cfg.kill_switch_at_pct:
            await self._event_bus.publish(
                DailyLossLimitBreached(
                    current_loss_pct=daily_loss_pct,
                    limit_pct=self._config.daily_loss.limit_pct,
                )
            )
            _log.critical(
                "portfolio_monitor.daily_loss_threshold_breached pct=%.1f threshold=%.1f (auto-activation disabled)",
                daily_loss_pct, cfg.kill_switch_at_pct,
            )

        _log.warning(
            "graduated_response_transition old=%s new=%s daily_loss_pct=%.1f",
            current_state,
            target_state,
            daily_loss_pct,
        )
