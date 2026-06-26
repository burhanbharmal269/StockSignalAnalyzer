"""EventCalendarService — Phase 21.1 §2.

Two responsibilities:
  1. Auto-seed NSE expiry events (called each scan cycle, idempotent upsert).
  2. Return a per-cycle event cache consumed by the scanner to compute per-signal
     confidence and sizing overlays.

Supported auto-event types
  NSE_EXPIRY_MONTHLY   — last Tuesday of month (expiry day, DTE=0)
  NSE_PREEXPIRY_MONTHLY — day before monthly expiry (DTE=1)
  NSE_EXPIRY_WEEKLY    — non-monthly Tuesday for NIFTY weekly (DTE=0)
  NSE_PREEXPIRY_WEEKLY — day before weekly expiry (DTE=1)

Manual event types (inserted via admin / API, not seeded here)
  RBI_MPC, BUDGET, FOMC, US_CPI, ELECTION, EARNINGS, SEBI_ACTION, CIRCUIT, OTHER

Severity overlays (configured in config/events.yaml):
  LOW      → conf_adj 0,  size 1.00, no pause
  MEDIUM   → conf_adj -3, size 0.85, no pause
  HIGH     → conf_adj -7, size 0.60, no pause
  CRITICAL → conf_adj -12, size 0.0, PAUSE auto execution
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Severity order for "worst first" comparison
_SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

# Default overlays matching config/events.yaml
_DEFAULT_SEVERITY_OVERLAYS: dict[str, dict] = {
    "LOW":      {"confidence_adj": 0.0,   "size_multiplier": 1.00, "pause_auto_execution": False},
    "MEDIUM":   {"confidence_adj": -3.0,  "size_multiplier": 0.85, "pause_auto_execution": False},
    "HIGH":     {"confidence_adj": -7.0,  "size_multiplier": 0.60, "pause_auto_execution": False},
    "CRITICAL": {"confidence_adj": -12.0, "size_multiplier": 0.00, "pause_auto_execution": True},
}

# IST offset for event time computation
_IST = timedelta(hours=5, minutes=30)
_SESSION_OPEN_IST  = time(9, 15)
_SESSION_CLOSE_IST = time(15, 30)

# Quarterly months (when monthly expiry = quarterly expiry)
_QUARTERLY_MONTHS = {3, 6, 9, 12}


@dataclass(frozen=True)
class EventOverlay:
    """Per-signal event overlay output."""
    events:               list[dict]
    worst_severity:       str
    confidence_adj:       float
    size_multiplier:      float
    pause_auto_execution: bool
    reason:               str
    event_types:          list[str] = field(default_factory=list)


def _last_tuesday_of_month(year: int, month: int) -> date:
    """Return the last Tuesday of the given month (NSE F&O monthly expiry)."""
    # Find any Tuesday in the last week of the month
    last_day = date(year, month, 28)
    while last_day.weekday() != 1:   # 1 = Tuesday
        last_day += timedelta(days=1)
    candidate = last_day
    while True:
        nxt = candidate + timedelta(days=7)
        if nxt.month != month:
            break
        candidate = nxt
    return candidate


def _ist_datetime(d: date, t: time) -> datetime:
    """Return an IST-aware datetime (stored as UTC in DB)."""
    naive = datetime.combine(d, t)
    return naive - _IST   # IST → UTC (subtract +05:30)


class EventCalendarService:
    """Event store + seeder for market event overlays."""

    def __init__(
        self,
        session_factory: "async_sessionmaker[AsyncSession]",
        seed_days_ahead: int = 7,
        active_window_minutes: int = 480,
    ) -> None:
        self._sf          = session_factory
        self._seed_days   = seed_days_ahead
        self._window_mins = active_window_minutes
        self._overlays    = _DEFAULT_SEVERITY_OVERLAYS

    # ------------------------------------------------------------------
    # Public — seeding
    # ------------------------------------------------------------------

    async def seed_nse_expiry_events(self) -> None:
        """Upsert NSE expiry and pre-expiry events for the next N days.

        Idempotent: uses ON CONFLICT DO UPDATE so re-running is harmless.
        Typically called once per scan cycle.
        """
        today_utc = datetime.now(UTC).date()
        today_ist = (datetime.now(UTC) + _IST).date()
        to_seed: list[dict] = []

        for offset in range(self._seed_days):
            check_ist = today_ist + timedelta(days=offset)
            year, month = check_ist.year, check_ist.month
            monthly_expiry = _last_tuesday_of_month(year, month)

            # Monthly or quarterly expiry day (DTE=0)
            if check_ist == monthly_expiry:
                is_quarterly = month in _QUARTERLY_MONTHS
                sev = "HIGH"   # monthly and quarterly both HIGH on DTE=0
                etype = "NSE_EXPIRY_MONTHLY"
                name  = (f"NSE {'Quarterly' if is_quarterly else 'Monthly'} Expiry "
                         f"{check_ist.strftime('%d-%b-%Y')}")
                to_seed.append(_event_row(etype, name, sev, check_ist))

            # Pre-expiry for monthly (DTE=1 from tomorrow)
            if (check_ist + timedelta(days=1)) == monthly_expiry:
                to_seed.append(_event_row(
                    "NSE_PREEXPIRY_MONTHLY",
                    f"Pre-Expiry (Monthly) {(check_ist + timedelta(days=1)).strftime('%d-%b-%Y')}",
                    "MEDIUM", check_ist,
                ))

            # NIFTY weekly expiry day (non-monthly Tuesday, DTE=0)
            if check_ist.weekday() == 1 and check_ist != monthly_expiry:
                to_seed.append(_event_row(
                    "NSE_EXPIRY_WEEKLY",
                    f"NIFTY Weekly Expiry {check_ist.strftime('%d-%b-%Y')}",
                    "MEDIUM", check_ist,
                ))

            # Pre-expiry for weekly (next day is weekly non-monthly Tuesday)
            nxt = check_ist + timedelta(days=1)
            if nxt.weekday() == 1 and nxt != _last_tuesday_of_month(nxt.year, nxt.month):
                to_seed.append(_event_row(
                    "NSE_PREEXPIRY_WEEKLY",
                    f"Pre-Weekly Expiry {nxt.strftime('%d-%b-%Y')}",
                    "LOW", check_ist,
                ))

        if not to_seed:
            return

        try:
            async with self._sf() as db:
                for row in to_seed:
                    await db.execute(
                        text("""
                            INSERT INTO event_calendar
                                (event_type, event_name, severity, affected_symbols,
                                 start_time, end_time, source, reason, is_active)
                            VALUES
                                (:etype, :name, :severity, NULL,
                                 :start_time, :end_time, 'AUTO', :reason, true)
                            ON CONFLICT (event_type, (start_time::date), source)
                            DO UPDATE SET
                                severity   = EXCLUDED.severity,
                                event_name = EXCLUDED.event_name,
                                is_active  = true
                        """),
                        row,
                    )
                await db.commit()
            _log.debug("event_calendar.seeded count=%d", len(to_seed))
        except Exception as exc:
            _log.warning("event_calendar.seed_failed: %s", exc)

    # ------------------------------------------------------------------
    # Public — query
    # ------------------------------------------------------------------

    async def get_global_event_cache(self, at: datetime) -> dict[str, list[dict]]:
        """Return active events keyed by symbol (None-key = affects all symbols).

        Format: {"ALL": [...], "NIFTY": [...], "HDFCBANK": [...]}
        Called ONCE per scan cycle; scanner applies per-symbol from cache.
        """
        window_end = at + timedelta(minutes=self._window_mins)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT event_type, event_name, severity,
                               affected_symbols, start_time, end_time, reason
                        FROM event_calendar
                        WHERE is_active = true
                          AND start_time <= :window_end
                          AND end_time   >= :at
                        ORDER BY severity DESC, start_time ASC
                    """),
                    {"at": at, "window_end": window_end},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("event_calendar.query_failed: %s", exc)
            return {}

        cache: dict[str, list[dict]] = {}
        for row in rows:
            event = {
                "event_type":  row[0],
                "event_name":  row[1],
                "severity":    row[2],
                "start_time":  row[4],
                "end_time":    row[5],
                "reason":      row[6],
            }
            affected = row[3]   # list or None
            if affected:
                for sym in affected:
                    cache.setdefault(str(sym), []).append(event)
            else:
                cache.setdefault("ALL", []).append(event)

        _log.debug(
            "event_calendar.cache_loaded keys=%s total_events=%d",
            list(cache.keys())[:5],
            sum(len(v) for v in cache.values()),
        )
        return cache

    def compute_overlay_from_cache(
        self,
        symbol: str,
        event_cache: dict[str, list[dict]],
    ) -> EventOverlay | None:
        """Compute EventOverlay for a symbol using the pre-fetched cache.

        Returns None when there are no active events for this symbol.
        """
        events = event_cache.get("ALL", []) + event_cache.get(symbol, [])
        if not events:
            return None

        worst = max(events, key=lambda e: _SEVERITY_ORDER.get(e["severity"], 0))
        sev   = worst["severity"]
        cfg   = self._overlays.get(sev, self._overlays["MEDIUM"])

        return EventOverlay(
            events               = events,
            worst_severity       = sev,
            confidence_adj       = cfg["confidence_adj"],
            size_multiplier      = cfg["size_multiplier"],
            pause_auto_execution = cfg["pause_auto_execution"],
            reason               = worst["event_name"],
            event_types          = list({e["event_type"] for e in events}),
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _event_row(event_type: str, name: str, severity: str, ist_date: date) -> dict:
    """Build a param dict for the upsert INSERT."""
    start_utc = _ist_datetime(ist_date, _SESSION_OPEN_IST)
    end_utc   = _ist_datetime(ist_date, _SESSION_CLOSE_IST)
    return {
        "etype":      event_type,
        "name":       name,
        "severity":   severity,
        "start_time": start_utc,
        "end_time":   end_utc,
        "reason":     f"NSE F&O auto-seeded: {name}",
    }
