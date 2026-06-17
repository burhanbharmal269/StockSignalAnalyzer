"""BrokerHealthService — probes broker endpoints and returns a BrokerHealthReport.

Probe sequence:
  1. connectivity   — broker.health_check() (no session required)
  2. auth           — broker.get_profile(session) (requires valid session)
  3. orders         — broker.get_orders(session)
  4. positions      — broker.get_positions(session)
  5. margin         — broker.get_margin(session)

Status:
  HEALTHY  = all 5 probes pass
  DEGRADED = probes 1+2 pass, but 3/4/5 partially fail
  DOWN     = probe 1 or 2 fails
"""

from __future__ import annotations

import logging
import time

from core.domain.value_objects.broker_health import BrokerHealthReport, BrokerHealthStatus

_log = logging.getLogger(__name__)


class BrokerHealthService:
    """Probes a broker adapter and returns a single BrokerHealthReport."""

    def __init__(self, broker: object) -> None:
        self._broker = broker

    async def check(self, session: object | None = None) -> BrokerHealthReport:
        """Run all probes and return a BrokerHealthReport.

        Args:
            session: Optional active BrokerSession. If None, only connectivity probe runs.
        """
        broker_name = getattr(self._broker, "broker_name", "unknown")
        details: dict = {}
        start = time.monotonic()

        # Probe 1: connectivity (no session)
        try:
            report = await self._broker.health_check()
            details["connectivity"] = "ok"
            details["connectivity_latency_ms"] = report.latency_ms
        except Exception as exc:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            _log.error(
                "BrokerHealthService.connectivity_probe_failed broker=%s error=%s",
                broker_name,
                exc,
            )
            return BrokerHealthReport(
                broker_name=broker_name,
                status=BrokerHealthStatus.DOWN,
                latency_ms=latency_ms,
                details=details,
                error=f"connectivity: {exc}",
            )

        if session is None:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            return BrokerHealthReport(
                broker_name=broker_name,
                status=BrokerHealthStatus.HEALTHY,
                latency_ms=latency_ms,
                details=details,
            )

        # Probe 2: auth
        authenticated_user: str | None = None
        try:
            profile = await self._broker.get_profile(session)
            details["auth"] = "ok"
            authenticated_user = profile.full_name or profile.user_id or None
        except Exception as exc:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            _log.error("BrokerHealthService.auth_probe_failed broker=%s error=%s", broker_name, exc)
            return BrokerHealthReport(
                broker_name=broker_name,
                status=BrokerHealthStatus.DOWN,
                latency_ms=latency_ms,
                details=details,
                error=f"auth: {exc}",
            )

        degraded_errors: list[str] = []
        authenticated_user: str | None = None

        # Probe 3: orders
        try:
            await self._broker.get_orders(session)
            details["orders"] = "ok"
        except Exception as exc:
            details["orders"] = "failed"
            degraded_errors.append(f"orders: {exc}")

        # Probe 4: positions
        try:
            await self._broker.get_positions(session)
            details["positions"] = "ok"
        except Exception as exc:
            details["positions"] = "failed"
            degraded_errors.append(f"positions: {exc}")

        # Probe 5: margin
        try:
            await self._broker.get_margin(session)
            details["margin"] = "ok"
        except Exception as exc:
            details["margin"] = "failed"
            degraded_errors.append(f"margin: {exc}")

        latency_ms = round((time.monotonic() - start) * 1000, 2)
        status = BrokerHealthStatus.DEGRADED if degraded_errors else BrokerHealthStatus.HEALTHY
        error = "; ".join(degraded_errors) if degraded_errors else None

        return BrokerHealthReport(
            broker_name=broker_name,
            status=status,
            latency_ms=latency_ms,
            details=details,
            error=error,
            authenticated_user=authenticated_user,
        )
